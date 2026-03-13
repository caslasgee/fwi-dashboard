# data.py
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from fire_risk.legacy.fwi_fri import get_fwi_xclim, categorize_fri, classify_fsi


# -------------------------------------------------------------------
# BASE DIRECTORY
# -------------------------------------------------------------------
# data.py is inside: fire_risk/legacy/data.py
# parents[2] points to your project root: FRI/
BASE_DIR = Path(__file__).resolve().parents[2]


# -------------------------------------------------------------------
# LOAD RAW DATA
# -------------------------------------------------------------------
equipment_df = pd.read_csv("Fire_Equipment_Map.csv")
aor_data = pd.read_excel(BASE_DIR / "AOR.xlsx")
aor_data.rename(columns={"New_Camp_Name": "CampName"}, inplace=True)

response_details = pd.read_excel(BASE_DIR / "CampResponseDetails.xlsx")

fire_data = pd.read_csv(BASE_DIR / "Fire Susceptability Data Block.csv")

# Standardize columns
equipment_df.columns = [c.strip() for c in equipment_df.columns]

# Clean key fields
equipment_df["Camp"] = equipment_df["Camp"].astype(str).str.strip()
equipment_df["Sub_block"] = equipment_df["Sub_block"].astype(str).str.strip()
equipment_df["Type_of facility"] = equipment_df["Type_of facility"].astype(str).str.strip()
equipment_df["Overall status"] = equipment_df["Overall status"].astype(str).str.strip()

# Coordinates
equipment_df["_LATITUDE"] = pd.to_numeric(equipment_df["_LATITUDE"], errors="coerce")
equipment_df["_LONGITUDE"] = pd.to_numeric(equipment_df["_LONGITUDE"], errors="coerce")

equipment_df = equipment_df.dropna(subset=["_LATITUDE", "_LONGITUDE"]).copy()

# Normalized helper fields
equipment_df["camp_key"] = equipment_df["Camp"].str.upper().str.strip()
equipment_df["block_key"] = equipment_df["Sub_block"].str.upper().str.strip()
equipment_df["facility_key"] = equipment_df["Type_of facility"].str.upper().str.strip()
equipment_df["status_key"] = equipment_df["Overall status"].str.upper().str.strip()

# Optional: cleaner status grouping
def normalize_status(x):
    x = str(x).strip().upper()
    if "FUNCTIONAL" in x and "NON" not in x:
        return "Functional"
    elif "NON" in x:
        return "Non-functional"
    elif x in ["", "NAN", "NONE"]:
        return "Unknown"
    return "Unknown"

equipment_df["status_group"] = equipment_df["Overall status"].apply(normalize_status)

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
        # Esri JSON style → normal GeoJSON Polygon
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


block_centroids = {}  # key: (camp, block) -> (lat, lon)


def _norm(s):
    return str(s).strip().upper() if pd.notna(s) else ""


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
        if not coords:
            continue

        ring = coords[0]
        if not ring:
            continue

        lons, lats = zip(*ring)
        centroid_lon = float(sum(lons) / len(lons))
        centroid_lat = float(sum(lats) / len(lats))

        block_centroids[(camp_key, block_key)] = (centroid_lat, centroid_lon)


def attach_block_centroid(row):
    """
    Replace camp-level lat/lon with block polygon centroid if available.
    Falls back to original lat/lon if no centroid match is found.
    """
    camp_key = _norm(row["CampName"])
    block_key = _norm(row["Block"])
    key = (camp_key, block_key)

    if key in block_centroids:
        lat, lon = block_centroids[key]
        return pd.Series({"Latitude": lat, "Longitude": lon})

    return pd.Series({"Latitude": row["Latitude"], "Longitude": row["Longitude"]})


# Apply centroids to cleaned_data
cleaned_data[["Latitude", "Longitude"]] = cleaned_data.apply(
    attach_block_centroid, axis=1
)


# -------------------------------------------------------------------
# CAMP-LEVEL SUMMARY (FSI, FWI, FRI)
# -------------------------------------------------------------------
camp_summary = (
    cleaned_data.groupby("CampName")[["Environment", "Fuel", "Behaviour", "Response"]]
    .mean()
    .reset_index()
)

camp_summary["FSI_Calculated"] = (
    camp_summary["Environment"]
    + camp_summary["Fuel"]
    + camp_summary["Behaviour"]
    + camp_summary["Response"]
) / 4

camp_summary = camp_summary.merge(
    aor_data[["CampName", "Latitude", "Longitude"]].drop_duplicates("CampName"),
    on="CampName",
    how="left",
)

camp_summary = camp_summary.dropna(subset=["Latitude", "Longitude"])


# -------------------------------------------------------------------
# CURRENT-DAY FWI / FRI
# -------------------------------------------------------------------
today_iso = date.today().isoformat()

camp_summary["FWI"] = camp_summary.apply(
    lambda row: math.ceil(
        get_fwi_xclim(row["Latitude"], row["Longitude"], date_for=today_iso)
    ),
    axis=1,
)

camp_summary["FRI"] = (
    camp_summary["FSI_Calculated"] * (1 + camp_summary["FWI"] / 100)
).round(1)

camp_summary["FRI_Class"] = camp_summary["FRI"].apply(categorize_fri)

cleaned_data["FSI_Class"] = cleaned_data["FSI_Calculated"].apply(classify_fsi)

# -------------------------------------------------------------------
# FIRE EQUIPMENT MAP DATA
# -------------------------------------------------------------------
equipment_df = pd.read_csv(BASE_DIR / "Fire_Equipment_Map.csv")

equipment_df.columns = [c.strip() for c in equipment_df.columns]

equipment_df["Camp"] = equipment_df["Camp"].astype(str).str.strip()
equipment_df["Sub_block"] = equipment_df["Sub_block"].astype(str).str.strip()
equipment_df["Type_of facility"] = equipment_df["Type_of facility"].astype(str).str.strip()
equipment_df["Overall status"] = equipment_df["Overall status"].astype(str).str.strip()

equipment_df["_LATITUDE"] = pd.to_numeric(equipment_df["_LATITUDE"], errors="coerce")
equipment_df["_LONGITUDE"] = pd.to_numeric(equipment_df["_LONGITUDE"], errors="coerce")

equipment_df = equipment_df.dropna(subset=["_LATITUDE", "_LONGITUDE"]).copy()

equipment_df["camp_key"] = equipment_df["Camp"].str.upper().str.strip()
equipment_df["block_key"] = equipment_df["Sub_block"].str.upper().str.strip()

def normalize_equipment_status(x):
    x = str(x).strip().upper()
    if "FUNCTIONAL" in x and "NON" not in x:
        return "Functional"
    elif "NON" in x:
        return "Non-functional"
    return "Unknown"

equipment_df["status_group"] = equipment_df["Overall status"].apply(normalize_equipment_status)