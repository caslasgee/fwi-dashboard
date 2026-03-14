from __future__ import annotations

import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import xarray as xr
import xclim
from dash import html
from xclim.indices.fire._cffwis import cffwis_indices

from fire_risk.legacy.config import (
    FRI_HIGH_MAX,
    FRI_LOW_MAX,
    FRI_MODERATE_MAX,
    FSI_HIGH_THRESHOLD,
    FSI_URGENT_THRESHOLD,
    FWI_HIGH_MAX,
    FWI_LOW_MAX,
    FWI_MODERATE_MAX,
)

xclim.set_options(data_validation="log")

# -------------------------------------------------------------------
# CACHES
# -------------------------------------------------------------------
fwi_cache: dict[tuple[float, float, str], float] = {}
monthly_fwi_cache: dict[tuple[float, float, int], list[float]] = {}


def degrees_to_compass(deg):
    if deg is None or pd.isna(deg):
        return "N/A"

    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    idx = int((float(deg) + 11.25) // 22.5) % 16
    return directions[idx]


# -------------------------------------------------------------------
# CATEGORY HELPERS
# -------------------------------------------------------------------
def categorize_fwi(fwi: float) -> str:
    if fwi < FWI_LOW_MAX:
        return "Low fire danger"
    elif fwi < FWI_MODERATE_MAX:
        return "Moderate fire danger"
    elif fwi < FWI_HIGH_MAX:
        return "High fire danger"
    return "Severe fire danger"



def categorize_fri(fri: float) -> str:
    if fri < FRI_LOW_MAX:
        return "Low risk"
    elif fri < FRI_MODERATE_MAX:
        return "Moderate risk"
    elif fri < FRI_HIGH_MAX:
        return "High risk"
    return "Extreme risk"


def compute_fri(fsi, fwi, round_result: bool = True):
    """
    Custom operational Fire Risk Index (FRI).

    Formula:
        FRI = FSI * (1 + FWI / 100)

    This is a dashboard-specific composite and not an official Canadian FWI
    System output. Keep the computation centralized here so the same formula is
    used consistently across current, forecast, and outlook views.
    """
    fri = pd.to_numeric(fsi, errors="coerce") * (1 + pd.to_numeric(fwi, errors="coerce") / 100.0)
    return fri.round(1) if round_result else fri



def classify_fsi(fsi: float) -> str:
    if fsi >= FSI_URGENT_THRESHOLD:
        return "Urgent"
    elif fsi >= FSI_HIGH_THRESHOLD:
        return "High"
    return "Moderate"


def _safe_float(value, default=np.nan):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _build_daily_weather_df_from_json(js, start_date, end_date):
    hourly = js.get("hourly", {}) or {}
    daily = js.get("daily", {}) or {}

    times = hourly.get("time", []) or []
    temps = hourly.get("temperature_2m", []) or []
    rhs = (
        hourly.get("relative_humidity_2m", [])
        or hourly.get("relativehumidity_2m", [])
        or []
    )
    winds = (
        hourly.get("wind_speed_10m", [])
        or hourly.get("windspeed_10m", [])
        or []
    )
    wind_dirs = (
        hourly.get("wind_direction_10m", [])
        or hourly.get("winddirection_10m", [])
        or []
    )

    daily_times = daily.get("time", []) or []
    daily_precip = daily.get("precipitation_sum", []) or []
    precip_map = {d: _safe_float(p, 0.0) for d, p in zip(daily_times, daily_precip)}

    rows = []
    for d in pd.date_range(start_date, end_date, freq="D"):
        iso_date = d.date().isoformat()
        target_time = f"{iso_date}T13:00"

        try:
            idx = times.index(target_time)
            temp = temps[idx] if idx < len(temps) else np.nan
            rh = rhs[idx] if idx < len(rhs) else np.nan
            wind = winds[idx] if idx < len(winds) else np.nan
            wind_dir_deg = wind_dirs[idx] if idx < len(wind_dirs) else np.nan
        except ValueError:
            idxs = [i for i, t in enumerate(times) if str(t).startswith(iso_date)]
            if idxs:
                temp_vals = [temps[i] for i in idxs if i < len(temps)]
                rh_vals = [rhs[i] for i in idxs if i < len(rhs)]
                wind_vals = [winds[i] for i in idxs if i < len(winds)]
                dir_vals = [
                wind_dirs[i] for i in idxs
                if i < len(wind_dirs) and wind_dirs[i] is not None and not pd.isna(wind_dirs[i])]
                wind_dir_deg = np.nanmean(dir_vals) if dir_vals else np.nan
                temp = max(temp_vals) if temp_vals else np.nan
                rh = np.nanmean(rh_vals) if rh_vals else np.nan
                wind = np.nanmean(wind_vals) if wind_vals else np.nan
            else:
                temp = rh = wind = wind_dir_deg = np.nan

        rows.append(
            {
                "date": iso_date,
                "temp": round(_safe_float(temp), 1) if pd.notna(_safe_float(temp)) else np.nan,
                "rh": round(_safe_float(rh), 1) if pd.notna(_safe_float(rh)) else np.nan,
                "wind": round(_safe_float(wind), 1) if pd.notna(_safe_float(wind)) else np.nan,
                "wind_dir_deg": round(_safe_float(wind_dir_deg), 1) if pd.notna(_safe_float(wind_dir_deg)) else np.nan,
                "wind_dir_label": degrees_to_compass(wind_dir_deg),
                "precip": round(_safe_float(precip_map.get(iso_date, 0.0), 0.0), 1),
            }
        )

    return pd.DataFrame(rows)


def get_historical_daily_weather(lat, lon, start_date, end_date):
    """
    Build a historical/recent daily weather series from Open-Meteo archive
    using noon-like hourly values + daily precipitation.
    """
    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date).date()
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date).date()

    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
        f"&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m"
        f"&daily=precipitation_sum"
        f"&wind_speed_unit=kmh"
        f"&timezone=auto"
    )

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        js = resp.json()
        return _build_daily_weather_df_from_json(js, start_date, end_date)
    except Exception as e:
        print(f"[WARN] Historical Open-Meteo weather failed for ({lat}, {lon}): {repr(e)}")
        return pd.DataFrame(columns=["date", "temp", "rh", "wind", "wind_dir_deg", "wind_dir_label", "precip"])

# -------------------------------------------------------------------
# CURRENT-DAY WEATHER (OPEN-METEO)
# -------------------------------------------------------------------
def get_weather_noon(lat, lon, iso_date):
    """
    Return local 13:00 temperature, RH, wind speed, wind direction,
    and daily precipitation using Open-Meteo.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={iso_date}&end_date={iso_date}"
        f"&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m"
        f"&daily=precipitation_sum"
        f"&wind_speed_unit=kmh"
        f"&timezone=auto"
    )

    last_error = None
    for _ in range(3):
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            js = resp.json()

            hourly = js.get("hourly", {})
            daily = js.get("daily", {})

            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            rhs = hourly.get("relative_humidity_2m", []) or hourly.get("relativehumidity_2m", [])
            winds = hourly.get("wind_speed_10m", []) or hourly.get("windspeed_10m", [])
            wind_dirs = hourly.get("wind_direction_10m", []) or hourly.get("winddirection_10m", [None] * len(times))

            try:
                idx = times.index(f"{iso_date}T13:00")
                temp = temps[idx] if idx < len(temps) else None
                rh = rhs[idx] if idx < len(rhs) else None
                wind = winds[idx] if idx < len(winds) else None
                wind_dir_deg = wind_dirs[idx] if idx < len(wind_dirs) else None
            except ValueError:
                day_idxs = [i for i, t in enumerate(times) if t.startswith(iso_date)]
                temp_vals = [temps[i] for i in day_idxs if i < len(temps)]
                rh_vals = [rhs[i] for i in day_idxs if i < len(rhs)]
                wind_vals = [winds[i] for i in day_idxs if i < len(winds)]
                dir_vals = [wind_dirs[i] for i in day_idxs if i < len(wind_dirs)]

                temp = max(temp_vals) if temp_vals else None
                rh = float(sum(rh_vals) / len(rh_vals)) if rh_vals else None
                wind = float(sum(wind_vals) / len(wind_vals)) if wind_vals else None
                valid_dirs = [d for d in dir_vals if d is not None and not pd.isna(d)]
                wind_dir_deg = float(sum(valid_dirs) / len(valid_dirs)) if valid_dirs else None

            precip_vals = daily.get("precipitation_sum", [0])
            precip = precip_vals[0] if precip_vals else 0

            return {
                "temp": round(float(temp), 1) if temp is not None else "N/A",
                "rh": round(float(rh), 1) if rh is not None else "N/A",
                "wind": round(float(wind), 1) if wind is not None else "N/A",
                "precip": round(float(precip), 1) if precip is not None else 0,
                "wind_dir_deg": round(float(wind_dir_deg), 1) if wind_dir_deg is not None else None,
                "wind_dir_label": degrees_to_compass(wind_dir_deg),
                "source_status": "live",
            }
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep(1)

    print(f"[WARN] Open-Meteo weather request failed for ({lat}, {lon}) on {iso_date}: {repr(last_error)}")
    return {
        "temp": "N/A",
        "rh": "N/A",
        "wind": "N/A",
        "precip": 0,
        "wind_dir_deg": None,
        "wind_dir_label": "N/A",
        "source_status": "fallback",
    }


# -------------------------------------------------------------------
# DAILY FWI (XCLIM CFFWIS)
# -------------------------------------------------------------------
def get_fwi_xclim(lat, lon, date_for=None, ffmc_init=None, dmc_init=None, dc_init=None):
    """
    Compute daily FWI using rolling prior-day FFMC/DMC/DC when initials are not supplied.
    """
    iso = date_for if date_for else date.today().isoformat()
    key = (round(lat, 4), round(lon, 4), iso)
    if key in fwi_cache:
        return fwi_cache[key]

    if ffmc_init is None or dmc_init is None or dc_init is None:
        prev_day = pd.to_datetime(iso).date() - timedelta(days=1)
        state = get_rolling_observed_fire_state(lat, lon, lookback_days=90, end_date=prev_day)
        ffmc_init = state["ffmc"]
        dmc_init = state["dmc"]
        dc_init = state["dc"]

    w = get_weather_noon(lat, lon, iso)
    if w["temp"] == "N/A" or w["rh"] == "N/A" or w["wind"] == "N/A":
        fwi_cache[key] = 0.0
        return 0.0

    one_day = pd.DataFrame(
        [{
            "date": iso,
            "temp": w["temp"],
            "rh": w["rh"],
            "wind": w["wind"],
            "precip": w["precip"],
        }]
    )

    out = compute_fwi_sequence_xclim(
        one_day,
        lat=lat,
        ffmc0=float(ffmc_init),
        dmc0=float(dmc_init),
        dc0=float(dc_init),
    )

    fwi_value = float(out["FWI"].iloc[0]) if not out.empty else 0.0
    fwi_cache[key] = fwi_value
    return fwi_value

# -------------------------------------------------------------------
# MONTHLY FWI (NASA POWER -> XCLIM)
# -------------------------------------------------------------------
def _safe_power_year(year: int | None = None) -> int:
    today = date.today()
    if year is None:
        year = today.year
    if year >= today.year:
        return today.year - 1
    return year



def _power_monthly_url(lat, lon, year):
    return (
        f"https://power.larc.nasa.gov/api/temporal/monthly/point"
        f"?start={year}&end={year}"
        f"&latitude={lat}&longitude={lon}"
        f"&community=sb"
        f"&parameters=T2M,RH2M,WS10M,PRECTOTCORR"
        f"&format=json"
        f"&user=chatgpt"
    )



def _power_climatology_url(lat, lon):
    return (
        f"https://power.larc.nasa.gov/api/temporal/climatology/point"
        f"?start=1991&end=2020"
        f"&latitude={lat}&longitude={lon}"
        f"&community=sb"
        f"&parameters=T2M,RH2M,WS10M,PRECTOTCORR"
        f"&format=json"
        f"&user=chatgpt"
    )



def get_monthly_fwi_xclim(lat, lon, year=None, ffmc_init=85.0, dmc_init=6.0, dc_init=15.0):
    """
    Build a daily synthetic year from NASA POWER monthly climate,
    run CFFWIS daily across the year, then aggregate to monthly mean FWI.
    """
    year = _safe_power_year(year)
    key = (round(lat, 4), round(lon, 4), year)
    if key in monthly_fwi_cache:
        return monthly_fwi_cache[key]

    keys = [f"{year}{month:02d}" for month in range(1, 13)]
    tas_vals = [None] * 12
    hurs_vals = [None] * 12
    wind_vals = [None] * 12
    pr_totals = [None] * 12

    try:
        resp = requests.get(_power_monthly_url(lat, lon, year), timeout=20)
        resp.raise_for_status()
        params = resp.json()["properties"]["parameter"]

        def safe_get(param, k):
            return params.get(param, {}).get(k, None)

        tas_vals = [safe_get("T2M", k) for k in keys]
        hurs_vals = [safe_get("RH2M", k) for k in keys]
        wind_vals = [safe_get("WS10M", k) for k in keys]
        pr_totals = [safe_get("PRECTOTCORR", k) for k in keys]
    except requests.RequestException:
        pass

    try:
        missing = [i for i, v in enumerate(tas_vals) if v is None]
        if missing:
            resp = requests.get(_power_climatology_url(lat, lon), timeout=20)
            resp.raise_for_status()
            params = resp.json()["properties"]["parameter"]
            for i in missing:
                m = f"{i + 1:02d}"
                tas_vals[i] = params["T2M"][m]
                hurs_vals[i] = params["RH2M"][m]
                wind_vals[i] = params["WS10M"][m]
                pr_totals[i] = params["PRECTOTCORR"][m]
    except requests.RequestException as e:
        raise RuntimeError(f"Unable to retrieve monthly climate data for ({lat}, {lon}).") from e

    rows = []
    for dt in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D"):
        m_idx = dt.month - 1
        days_in_month = dt.days_in_month

        rows.append(
            {
                "date": dt.date().isoformat(),
                "temp": _safe_float(tas_vals[m_idx]),
                "rh": _safe_float(hurs_vals[m_idx]),
                "wind": _safe_float(wind_vals[m_idx]) * 3.6,   # m/s -> km/h if needed by your source
                "precip": _safe_float(pr_totals[m_idx]) / days_in_month,
            }
        )

    daily_df = pd.DataFrame(rows)
    seq = compute_fwi_sequence_xclim(
        daily_df,
        lat=lat,
        ffmc0=ffmc_init,
        dmc0=dmc_init,
        dc0=dc_init,
    )

    monthly_fwi = (
        seq.assign(Month=pd.to_datetime(seq["date"]).dt.month)
        .groupby("Month")["FWI"]
        .mean()
        .reindex(range(1, 13))
        .fillna(0.0)
        .round(1)
        .tolist()
    )

    monthly_fwi_cache[key] = monthly_fwi
    return monthly_fwi

# -------------------------------------------------------------------
# NARRATIVE HELPERS
# -------------------------------------------------------------------
def explain_fri_value(fri_value: int) -> str:
    cls = categorize_fri(fri_value)
    if cls == "Low risk":
        return (
            f"{fri_value} falls in the LOW risk band: fire outbreaks are less likely, "
            "but basic preparedness should still be maintained."
        )
    elif cls == "Moderate risk":
        return (
            f"{fri_value} is a MODERATE risk: conditions allow fires to spread if they start. "
            "Extra attention to safe cooking, LPG handling and detection is advised."
        )
    elif cls == "High risk":
        return (
            f"{fri_value} is a HIGH risk: a single fire could spread quickly between shelters. "
            "Readiness of volunteers, access and rapid suppression should be prioritised."
        )
    return (
        f"{fri_value} is an EXTREME risk: even small ignitions can become large incidents. "
        "Fire-prone activities should be reduced and contingency plans reviewed with the community."
    )



def explain_fwi_value(fwi_value: int) -> str:
    cls = categorize_fwi(fwi_value)
    if cls == "Low fire danger":
        return (
            f"{fwi_value} indicates LOW fire-weather danger: cooler, more humid or less windy "
            "conditions mean fires are less likely to ignite or spread rapidly."
        )
    elif cls == "Moderate fire danger":
        return (
            f"{fwi_value} indicates MODERATE fire-weather danger: conditions may allow fires "
            "to grow once ignited, particularly in dry areas."
        )
    elif cls == "High fire danger":
        return (
            f"{fwi_value} indicates HIGH fire-weather danger: dry fuels and wind can allow "
            "fires to spread quickly after ignition."
        )
    return (
        f"{fwi_value} indicates SEVERE fire-weather danger: very hot, dry and/or windy "
        "weather means any fire can spread rapidly and become difficult to control."
    )



def build_current_risk_narrative(selected_camp: str, df_fri: pd.DataFrame):
    total = len(df_fri)
    row = df_fri.loc[df_fri["CampName"] == selected_camp].iloc[0]
    fri = int(row["FRI"])
    cls = row["FRI_Class"]

    df_sorted = df_fri.sort_values("FRI", ascending=False).reset_index(drop=True)
    rank = int(df_sorted.index[df_sorted["CampName"] == selected_camp][0]) + 1
    percentile = round(100 * (total - rank) / (total - 1)) if total > 1 else 0

    counts = df_fri["FRI_Class"].value_counts().to_dict()
    extreme = counts.get("Extreme risk", 0)
    high = counts.get("High risk", 0)
    moderate = counts.get("Moderate risk", 0)
    low = counts.get("Low risk", 0)

    return html.Div([
        html.H5("Current Fire Risk Summary", style={"fontWeight": "bold"}),
        html.P(
            f"Today, {selected_camp} has a Fire Risk Index (FRI) of {fri} ({cls}), "
            f"ranking {rank} out of {total} camps (around the top {percentile}%).",
            style={"fontSize": "14px"},
        ),
        html.P(explain_fri_value(fri), style={"fontSize": "14px"}),
        html.P(
            f"Across all sites today: {extreme} camp(s) are in Extreme, {high} in High, "
            f"{moderate} in Moderate and {low} in Low risk.",
            style={"fontSize": "14px"},
        ),
    ])



def build_current_weather_narrative(selected_camp: str, df_fwi: pd.DataFrame):
    total = len(df_fwi)
    row = df_fwi.loc[df_fwi["CampName"] == selected_camp].iloc[0]
    fwi = int(row["FWI"])
    cls = categorize_fwi(fwi)

    df_sorted = df_fwi.sort_values("FWI", ascending=False).reset_index(drop=True)
    rank = int(df_sorted.index[df_sorted["CampName"] == selected_camp][0]) + 1
    percentile = round(100 * (total - rank) / (total - 1)) if total > 1 else 0

    df_local = df_fwi.copy()
    df_local["Risk"] = df_local["FWI"].apply(categorize_fwi)
    counts = df_local["Risk"].value_counts().to_dict()
    low = counts.get("Low fire danger", 0)
    moderate = counts.get("Moderate fire danger", 0)
    high = counts.get("High fire danger", 0)
    severe = counts.get("Severe fire danger", 0)

    return html.Div([
        html.H5("Current Fire Weather Summary", style={"fontWeight": "bold"}),
        html.P(
            f"Today, {selected_camp} has a Fire Weather Index (FWI) of {fwi} ({cls}), "
            f"ranking {rank} out of {total} camps (around the top {percentile}%).",
            style={"fontSize": "14px"},
        ),
        html.P(explain_fwi_value(fwi), style={"fontSize": "14px"}),
        html.P(
            f"Across all sites: {severe} camp(s) are in Severe, {high} in High, "
            f"{moderate} in Moderate and {low} in Low fire-weather danger.",
            style={"fontSize": "14px"},
        ),
    ])



def build_monthly_risk_narrative(selected_camp: str, df_month: pd.DataFrame, value_col: str, index_name: str):
    peak_row = df_month.loc[df_month[value_col].idxmax()]
    low_row = df_month.loc[df_month[value_col].idxmin()]
    high_like = df_month[df_month["risk"].isin(["High risk", "Extreme risk", "High fire danger", "Severe fire danger"])]
    moderate_like = df_month[df_month["risk"].isin(["Moderate risk", "Moderate fire danger"])]

    return html.Div([
        html.H5(f"Monthly {index_name}", style={"fontWeight": "bold"}),
        html.P(
            f"For {selected_camp}, the highest monthly {index_name} occurs in {peak_row['month']} "
            f"(value {int(peak_row[value_col])}), while the lowest occurs in {low_row['month']} "
            f"({int(low_row[value_col])}).",
            style={"fontSize": "14px"},
        ),
        html.P(
            f"Over the year, {len(high_like)} month(s) reach High/Severe bands and {len(moderate_like)} are in Moderate bands.",
            style={"fontSize": "14px"},
        ),
    ])



def build_forecast_narrative(selected_camp: str, df_fc: pd.DataFrame, value_col: str, index_name: str):
    counts = df_fc["Risk"].value_counts().to_dict()
    low = counts.get("Low risk", 0) + counts.get("Low fire danger", 0)
    moderate = counts.get("Moderate risk", 0) + counts.get("Moderate fire danger", 0)
    high = counts.get("High risk", 0) + counts.get("High fire danger", 0)
    extreme = counts.get("Extreme risk", 0)
    severe = counts.get("Severe fire danger", 0)

    high_like = df_fc[df_fc["Risk"].isin(["High risk", "Extreme risk", "High fire danger", "Severe fire danger"])]
    if not high_like.empty:
        first_peak = high_like.iloc[0]
        first_peak_text = (
            f"The first high-danger day is {first_peak['Date']} "
            f"({index_name} ≈ {int(round(first_peak[value_col]))}, {first_peak['Risk']})."
        )
    else:
        first_peak_text = "No High/Severe days are forecast in the next 14 days."

    return html.Div([
        html.H5(f"14-Day {index_name} Forecast", style={"fontWeight": "bold"}),
        html.P(
            f"Over the next 14 days in {selected_camp}, the forecast shows: {extreme + severe} day(s) in the highest danger band, "
            f"{high} in High, {moderate} in Moderate and {low} in Low.",
            style={"fontSize": "14px"},
        ),
        html.P(first_peak_text, style={"fontSize": "14px"}),
        html.P(
            "Use this outlook to plan staff presence, drills, messaging and checks on critical equipment in the days where danger is highest.",
            style={"fontSize": "14px"},
        ),
    ])


# -------------------------------------------------------------------
# 14-DAY FORECAST WEATHER (OPEN-METEO)
# -------------------------------------------------------------------
def get_openmeteo_14day_weather(lat, lon, start_date=None, horizon=14):
    if start_date is None:
        start_date = date.today() + timedelta(days=1)
    end_date = start_date + timedelta(days=horizon - 1)

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
        f"&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m"
        f"&daily=precipitation_sum"
        f"&wind_speed_unit=kmh"
        f"&timezone=auto"
    )

    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        js = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[WARN] 14-day Open-Meteo forecast failed: {repr(e)}")
        return pd.DataFrame(columns=["date", "temp", "rh", "wind", "wind_dir_deg", "wind_dir_label", "precip"])

    hourly = js.get("hourly", {})
    daily = js.get("daily", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    rhs = hourly.get("relative_humidity_2m", []) or hourly.get("relativehumidity_2m", [])
    winds = hourly.get("wind_speed_10m", []) or hourly.get("windspeed_10m", [])
    wind_dirs = hourly.get("wind_direction_10m", []) or hourly.get("winddirection_10m", [])
    precip_map = {d: p for d, p in zip(daily.get("time", []), daily.get("precipitation_sum", []))}

    rows = []
    for d in pd.date_range(start_date, end_date, freq="D"):
        iso_date = d.date().isoformat()
        target_time = f"{iso_date}T13:00"
        try:
            idx = times.index(target_time)
            temp = temps[idx] if idx < len(temps) else None
            rh = rhs[idx] if idx < len(rhs) else None
            wind = winds[idx] if idx < len(winds) else None
            wind_dir_deg = wind_dirs[idx] if idx < len(wind_dirs) else None
        except ValueError:
            idxs = [i for i, t in enumerate(times) if t.startswith(iso_date)]
            if idxs:
                temp_vals = [temps[i] for i in idxs if i < len(temps)]
                rh_vals = [rhs[i] for i in idxs if i < len(rhs)]
                dir_vals = [
                wind_dirs[i] for i in idxs
                if i < len(wind_dirs) and wind_dirs[i] is not None and not pd.isna(wind_dirs[i])]
                wind_dir_deg = float(sum(dir_vals) / len(dir_vals)) if dir_vals else None
                wind_vals = [winds[i] for i in idxs if i < len(winds)]
                temp = max(temp_vals) if temp_vals else None
                rh = float(sum(rh_vals) / len(rh_vals)) if rh_vals else None
                wind = float(sum(wind_vals) / len(wind_vals)) if wind_vals else None
            else:
                temp = rh = wind = wind_dir_deg = None

        rows.append({
            "date": iso_date,
            "temp": round(float(temp), 1) if temp is not None else np.nan,
            "rh": round(float(rh), 1) if rh is not None else np.nan,
            "wind": round(float(wind), 1) if wind is not None else np.nan,
            "wind_dir_deg": round(float(wind_dir_deg), 1) if wind_dir_deg is not None else np.nan,
            "wind_dir_label": degrees_to_compass(wind_dir_deg),
            "precip": round(float(precip_map.get(iso_date, 0) or 0), 1),
        })

    return pd.DataFrame(rows)


# -------------------------------------------------------------------
# STATEFUL MULTI-DAY FWI SEQUENCE
# -------------------------------------------------------------------
def compute_fwi_sequence_xclim(weather_df, lat, ffmc0=85.0, dmc0=6.0, dc0=15.0):
    """
    Compute a stateful multi-day FWI sequence using xclim CFFWIS.
    """
    if weather_df.empty:
        out = weather_df.copy()
        for col in ["DC", "DMC", "FFMC", "ISI", "BUI", "FWI", "FWI_Risk"]:
            out[col] = []
        return out

    work = weather_df.copy()
    work["date"] = pd.to_datetime(work["date"])
    for col in ["temp", "rh", "wind", "precip"]:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    work = work.dropna(subset=["date", "temp", "rh", "wind", "precip"]).sort_values("date").reset_index(drop=True)

    if work.empty:
        out = weather_df.copy()
        out["DC"] = np.nan
        out["DMC"] = np.nan
        out["FFMC"] = np.nan
        out["ISI"] = np.nan
        out["BUI"] = np.nan
        out["FWI"] = np.nan
        out["FWI_Risk"] = None
        return out

    times = pd.to_datetime(work["date"])

    da_tas = xr.DataArray(work["temp"].to_numpy(), dims=("time",), coords={"time": times}, name="tas", attrs={"units": "degC"})
    da_hurs = xr.DataArray(work["rh"].to_numpy(), dims=("time",), coords={"time": times}, name="hurs", attrs={"units": "%"})
    da_wind = xr.DataArray(work["wind"].to_numpy(), dims=("time",), coords={"time": times}, name="sfcWind", attrs={"units": "km/h"})
    da_pr = xr.DataArray(work["precip"].to_numpy(), dims=("time",), coords={"time": times}, name="pr", attrs={"units": "mm/d"})
    da_lat = xr.DataArray(lat, attrs={"units": "degrees_north"})
    da_ffmc0 = xr.DataArray(ffmc0, attrs={"units": "1"})
    da_dmc0 = xr.DataArray(dmc0, attrs={"units": "1"})
    da_dc0 = xr.DataArray(dc0, attrs={"units": "1"})

    dc, dmc, ffmc, isi, bui, fwi = cffwis_indices(
        tas=da_tas,
        pr=da_pr,
        sfcWind=da_wind,
        hurs=da_hurs,
        lat=da_lat,
        ffmc0=da_ffmc0,
        dmc0=da_dmc0,
        dc0=da_dc0,
    )

    out = work.copy()
    out["DC"] = np.round(np.asarray(dc.values), 1)
    out["DMC"] = np.round(np.asarray(dmc.values), 1)
    out["FFMC"] = np.round(np.asarray(ffmc.values), 1)
    out["ISI"] = np.round(np.asarray(isi.values), 1)
    out["BUI"] = np.round(np.asarray(bui.values), 1)
    out["FWI"] = np.round(np.asarray(fwi.values), 1)
    out["FWI_Risk"] = out["FWI"].apply(categorize_fwi)
    out["date"] = out["date"].dt.date.astype(str)
    return out

def get_rolling_observed_fire_state(lat, lon, lookback_days=90, end_date=None):
    """
    Reconstruct the most recent FFMC/DMC/DC using observed historical weather.
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    elif isinstance(end_date, str):
        end_date = pd.to_datetime(end_date).date()

    start_date = end_date - timedelta(days=max(lookback_days - 1, 0))
    hist_df = get_historical_daily_weather(lat, lon, start_date, end_date)

    if hist_df.empty:
        return {
            "ffmc": 85.0,
            "dmc": 6.0,
            "dc": 15.0,
            "fwi": 0.0,
            "as_of": end_date.isoformat(),
            "source_status": "fallback",
        }

    seq = compute_fwi_sequence_xclim(hist_df, lat=lat, ffmc0=85.0, dmc0=6.0, dc0=15.0)
    last = seq.iloc[-1]

    return {
        "ffmc": float(last["FFMC"]),
        "dmc": float(last["DMC"]),
        "dc": float(last["DC"]),
        "fwi": float(last["FWI"]),
        "as_of": str(last["date"]),
        "source_status": "live",
    }

# -------------------------------------------------------------------
# SHORT-TERM FSI ADJUSTMENT + FRI FORECAST
# -------------------------------------------------------------------
def apply_dynamic_fsi_adjustment(forecast_df, base_fsi):
    if forecast_df.empty:
        out = forecast_df.copy()
        out["Adjusted_FSI"] = np.nan
        out["FRI"] = np.nan
        out["FRI_Risk"] = None
        return out

    out = forecast_df.copy()
    dryness_streak = 0
    adjusted_fsis = []

    for _, row in out.iterrows():
        precip = float(row["precip"]) if pd.notna(row["precip"]) else 0.0
        wind = float(row["wind"]) if pd.notna(row["wind"]) else 0.0
        rh = float(row["rh"]) if pd.notna(row["rh"]) else 50.0

        dryness_streak = dryness_streak + 1 if precip < 1.0 else 0
        dryness_bonus = min(dryness_streak * 1.5, 8.0)
        wind_bonus = min(max(wind - 20.0, 0.0) * 0.2, 5.0)
        humidity_bonus = min(max(45.0 - rh, 0.0) * 0.15, 5.0)
        rain_penalty = min(precip * 0.8, 6.0)

        adjusted_fsi = base_fsi + dryness_bonus + wind_bonus + humidity_bonus - rain_penalty
        adjusted_fsi = max(0.0, min(100.0, round(adjusted_fsi, 1)))
        adjusted_fsis.append(adjusted_fsi)

    out["Adjusted_FSI"] = adjusted_fsis
    out["FRI"] = compute_fri(out["Adjusted_FSI"], out["FWI"])
    out["FRI_Risk"] = out["FRI"].apply(categorize_fri)
    return out



def get_14day_fire_forecast(lat, lon, base_fsi, ffmc0=None, dmc0=None, dc0=None):
    """
    Full 14-day projected fire forecast warm-started from observed recent fire state.
    """
    weather_df = get_openmeteo_14day_weather(lat, lon)

    if weather_df.empty:
        return pd.DataFrame(columns=[
            "date", "Date", "temp", "rh", "wind", "wind_dir_deg", "wind_dir_label",
            "precip", "FFMC", "DMC", "DC", "ISI", "BUI", "FWI", "FWI_Risk",
            "Adjusted_FSI", "FRI", "FRI_Risk",
        ])

    if ffmc0 is None or dmc0 is None or dc0 is None:
        observed_state = get_rolling_observed_fire_state(
            lat,
            lon,
            lookback_days=90,
            end_date=date.today() - timedelta(days=1),
        )
        ffmc0 = observed_state["ffmc"]
        dmc0 = observed_state["dmc"]
        dc0 = observed_state["dc"]

    fwi_df = compute_fwi_sequence_xclim(
        weather_df,
        lat=lat,
        ffmc0=float(ffmc0),
        dmc0=float(dmc0),
        dc0=float(dc0),
    )

    out = apply_dynamic_fsi_adjustment(fwi_df, base_fsi=float(base_fsi))
    out["Date"] = pd.to_datetime(out["date"]).dt.strftime("%b %d")
    return out
