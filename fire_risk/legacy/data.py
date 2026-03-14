# data.py
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from fire_risk.legacy.fwi_fri import get_fwi_xclim, categorize_fri, classify_fsi, compute_fri
from fire_risk.services.cache import cache


# -------------------------------------------------------------------
# BASE DIRECTORY
# -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]


# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------
def _norm(s):
    return str(s).strip().upper() if pd.notna(s) else ""


def normalize_status(x):
    x = str(x).strip().upper()
    if "FUNCTIONAL" in x and "NON" not in x:
        return "Functional"
    elif "NON" in x:
        return "Non-functional"
    elif x in ["", "NAN", "NONE"]:
        return "Unknown"
    return "Unknown"


def load_equipment_data(base_dir: Path) -> pd.DataFrame:
    equipment = pd.read_csv(base_dir / "Fire_Equipment_Map.csv")
    equipment.columns = [c.strip() for c in equipment.columns]
    equipment["Camp"] = equipment["Camp"].astype(str).str.strip()
    equipment["Sub_block"] = equipment["Sub_block"].astype(str).str.strip()
    equipment["Type_of facility"] = equipment["Type_of facility"].astype(str).str.strip()
    equipment["Overall status"] = equipment["Overall status"].astype(str).str.strip()
    equipment["_LATITUDE"] = pd.to_numeric(equipment["_LATITUDE"], errors="coerce")
    equipment["_LONGITUDE"] = pd.to_numeric(equipment["_LONGITUDE"], errors="coerce")
    equipment = equipment.dropna(subset=["_LATITUDE", "_LONGITUDE"]).copy()
    equipment["camp_key"] = equipment["Camp"].str.upper().str.strip()
    equipment["block_key"] = equipment["Sub_block"].str.upper().str.strip()
    equipment["facility_key"] = equipment["Type_of facility"].str.upper().str.strip()
    equipment["status_key"] = equipment["Overall status"].str.upper().str.strip()
    equipment["status_group"] = equipment["Overall status"].apply(normalize_status)
    return equipment


# -------------------------------------------------------------------
# LOAD RAW DATA
# -------------------------------------------------------------------
equipment_df = load_equipment_data(BASE_DIR)
aor_data = pd.read_excel(BASE_DIR / "AOR.xlsx")
aor_data.rename(columns={"New_Camp_Name": "CampName"}, inplace=True)
response_details = pd.read_excel(BASE_DIR / "CampResponseDetails.xlsx")
fire_data = pd.read_csv(BASE_DIR / "Fire Susceptability Data Block.csv")


# -------------------------------------------------------------------
# CAMP OUTLINE GEOJSON
# -------------------------------------------------------------------
try:
    with open(BASE_DIR / "Camp_Outline.json", "r", encoding="utf-8") as f:
        geojson_data = json.load(f)
except FileNotFoundError:
    geojson_data = None

if geojson_data is not None:
    for feat in geojson_data["features"]:
        feat["geometry"] = {
            "type": "Polygon",
            "coordinates": feat["geometry"]["rings"],
        }
        feat["properties"] = feat.pop("attributes")


# -------------------------------------------------------------------
# MERGE FIRE DATA + AOR, FSI CALC
# -------------------------------------------------------------------
merged_data = pd.merge(fire_data, aor_data, on="CampName", how="left")
if "Block" not in merged_data.columns:
    raise ValueError("❌ 'Block' column not found in dataset! Please check the data.")

merged_data["FSI_Calculated"] = (
    merged_data["Environment"].fillna(0)
    + merged_data["Fuel"].fillna(0)
    + merged_data["Behaviour"].fillna(0)
    + merged_data["Response"].fillna(0)
) / 4
cleaned_data = merged_data.dropna(subset=["Latitude", "Longitude"]).copy()
cleaned_data["FSI_Class"] = cleaned_data["FSI_Calculated"].apply(classify_fsi)


# -------------------------------------------------------------------
# BLOCK OUTLINE GEOJSON + CENTROIDS
# -------------------------------------------------------------------
try:
    with open(BASE_DIR / "Block_Outline.json", "r", encoding="utf-8") as f:
        block_geo_raw = json.load(f)
except FileNotFoundError:
    block_geo_raw = None

block_geojson = None
if block_geo_raw is not None:
    for feat in block_geo_raw["features"]:
        feat["geometry"] = {
            "type": "Polygon",
            "coordinates": feat["geometry"]["rings"],
        }
        feat["properties"] = feat.pop("attributes")
    block_geojson = block_geo_raw

block_centroids = {}
if block_geojson is not None:
    for feat in block_geojson["features"]:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        camp_name = props.get("CampName_1") or props.get("CampName") or ""
        block_label = props.get("BlockLabel") or props.get("BlockName") or ""

        camp_key = _norm(camp_name)
        block_key = _norm(block_label)
        if not camp_key or not block_key:
            continue
        if geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates", [])
        if not coords or not coords[0]:
            continue

        ring = coords[0]
        lons, lats = zip(*ring)
        centroid_lon = float(sum(lons) / len(lons))
        centroid_lat = float(sum(lats) / len(lats))
        block_centroids[(camp_key, block_key)] = (centroid_lat, centroid_lon)


def attach_block_centroid(row):
    camp_key = _norm(row["CampName"])
    block_key = _norm(row["Block"])
    key = (camp_key, block_key)
    if key in block_centroids:
        lat, lon = block_centroids[key]
        return pd.Series({"Latitude": lat, "Longitude": lon})
    return pd.Series({"Latitude": row["Latitude"], "Longitude": row["Longitude"]})


cleaned_data[["Latitude", "Longitude"]] = cleaned_data.apply(attach_block_centroid, axis=1)


# -------------------------------------------------------------------
# CAMP-LEVEL SUMMARY BASE
# -------------------------------------------------------------------
def build_camp_summary_base() -> pd.DataFrame:
    summary = (
        cleaned_data.groupby("CampName")[["Environment", "Fuel", "Behaviour", "Response"]]
        .mean()
        .reset_index()
    )
    summary["FSI_Calculated"] = (
        summary["Environment"]
        + summary["Fuel"]
        + summary["Behaviour"]
        + summary["Response"]
    ) / 4
    summary = summary.merge(
        aor_data[["CampName", "Latitude", "Longitude"]].drop_duplicates("CampName"),
        on="CampName",
        how="left",
    )
    summary = summary.dropna(subset=["Latitude", "Longitude"]).copy()
    summary["FWI"] = np.nan
    summary["FRI"] = np.nan
    summary["FRI_Class"] = None
    return summary


def build_current_camp_summary(force_refresh: bool = False) -> pd.DataFrame:
    today_iso = date.today().isoformat()
    cache_key = f"camp_summary_live|date={today_iso}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached.copy()

    summary = build_camp_summary_base()
    summary["FWI"] = summary.apply(
        lambda row: round(get_fwi_xclim(row["Latitude"], row["Longitude"], date_for=today_iso), 1),
        axis=1,
    )
    summary["FRI"] = compute_fri(summary["FSI_Calculated"], summary["FWI"])
    summary["FRI_Class"] = summary["FRI"].apply(categorize_fri)
    cache.set(cache_key, summary, ttl_seconds=15 * 60)
    return summary.copy()


def get_live_camp_summary(force_refresh: bool = False) -> pd.DataFrame:
    return build_current_camp_summary(force_refresh=force_refresh)


camp_summary = build_camp_summary_base()
