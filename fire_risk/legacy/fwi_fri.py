from fire_risk.legacy.config import (
    FSI_URGENT_THRESHOLD,
    FSI_HIGH_THRESHOLD,
    FRI_LOW_MAX,
    FRI_MODERATE_MAX,
    FRI_HIGH_MAX,
    FWI_LOW_MAX,
    FWI_MODERATE_MAX,
    FWI_HIGH_MAX,
)

# fwi_fri.py
import math
from datetime import date, timedelta, datetime

import numpy as np
import pandas as pd
import requests
import xarray as xr
import xclim
from xclim.indices.fire._cffwis import cffwis_indices

# -------------------------------------------------------------------
# XCLIM CONFIG
# -------------------------------------------------------------------
xclim.set_options(data_validation="log")


def to_da(vals, dates, name, units):
    da = xr.DataArray(
        data=np.atleast_1d(vals),
        dims=("time",),
        coords={"time": dates},
        name=name,
    )
    da.attrs["units"] = units
    return da


# -------------------------------------------------------------------
# HOURLY WEATHER (Open-Meteo @ 13:00 local)
# -------------------------------------------------------------------
import time


def degrees_to_compass(deg):
    if deg is None or pd.isna(deg):
        return "N/A"

    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]
    idx = int((deg + 11.25) // 22.5) % 16
    return directions[idx]


def get_weather_noon(lat, lon, iso_date):
    """
    Returns temperature, RH, wind speed, wind direction, and daily precipitation.

    Safe fallback version:
    - tries Open-Meteo up to 3 times
    - if API/SSL/network fails, returns fallback values instead of crashing
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={iso_date}&end_date={iso_date}"
        f"&hourly=temperature_2m,relativehumidity_2m,windspeed_10m,winddirection_10m,precipitation"
        f"&daily=precipitation_sum"
        f"&timezone=auto"
    )

    last_error = None

    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            js = resp.json()

            hourly = js.get("hourly", {})
            daily = js.get("daily", {})

            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            rhs = hourly.get("relativehumidity_2m", [])
            winds = hourly.get("windspeed_10m", [])
            wind_dirs = hourly.get("winddirection_10m", [None] * len(times))

            try:
                idx = times.index(f"{iso_date}T13:00")
                temp = temps[idx] if idx < len(temps) else None
                rh = rhs[idx] if idx < len(rhs) else None
                wind = winds[idx] if idx < len(winds) else None
                wind_dir_deg = wind_dirs[idx] if idx < len(wind_dirs) else None
            except ValueError:
                temp = max(temps) if temps else None
                rh = sum(rhs) / len(rhs) if rhs else None
                wind = sum(winds) / len(winds) if winds else None

                valid_dirs = [d for d in wind_dirs if d is not None and not pd.isna(d)]
                wind_dir_deg = round(sum(valid_dirs) / len(valid_dirs), 1) if valid_dirs else None

            precip_list = daily.get("precipitation_sum", [0])
            precip = precip_list[0] if precip_list else 0

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
# DAILY FIRE WEATHER INDEX (XCLIM CFFWIS)
# -------------------------------------------------------------------
fwi_cache = {}


def get_fwi_xclim(
    lat,
    lon,
    date_for=None,
    ffmc_init=85.0,
    dmc_init=6.0,
    dc_init=15.0,
):
    """
    Compute FWI for a single day using xclim's Canadian Forest Fire Weather
    Index System (CFFWIS), driven by Open-Meteo weather at 13:00 local time.
    Cached by (lat, lon, date).
    """
    iso = date_for if date_for else date.today().isoformat()
    key = (round(lat, 4), round(lon, 4), iso)
    if key in fwi_cache:
        return fwi_cache[key]

    w = get_weather_noon(lat, lon, iso)
    if w["temp"] == "N/A" or w["rh"] == "N/A" or w["wind"] == "N/A":
        return 0.0
    times = pd.date_range(start=iso, periods=1)

    da_tas = to_da([w["temp"]], times, "tas", "°C")
    da_pr = to_da([w["precip"]], times, "pr", "mm d-1")
    da_wind = to_da([w["wind"]], times, "sfcWind", "km/h")
    da_hurs = to_da([w["rh"]], times, "hurs", "%")
    da_lat = xr.DataArray(lat, name="lat", attrs={"units": "degrees_north"})

    da_ffmc0 = xr.DataArray(ffmc_init, name="ffmc0", attrs={"units": "1"})
    da_dmc0 = xr.DataArray(dmc_init, name="dmc0", attrs={"units": "mm"})
    da_dc0 = xr.DataArray(dc_init, name="dc0", attrs={"units": "mm"})

    (
        drought_code,
        duff_moisture_code,
        fine_fuel_moisture_code,
        initial_spread_index,
        buildup_index,
        fire_weather_index,
    ) = cffwis_indices(
        tas=da_tas,
        pr=da_pr,
        sfcWind=da_wind,
        hurs=da_hurs,
        lat=da_lat,
        ffmc0=da_ffmc0,
        dmc0=da_dmc0,
        dc0=da_dc0,
    )

    fwi_value = float(fire_weather_index.values[0])
    fwi_cache[key] = fwi_value
    return fwi_value


# -------------------------------------------------------------------
# MONTHLY FIRE WEATHER INDEX (NASA POWER → XCLIM)
# -------------------------------------------------------------------
monthly_fwi_cache = {}

def _safe_power_year(year: int | None = None) -> int:
    today = date.today()
    if year is None:
        year = today.year

    # For a 12-month monthly series, avoid current/future year.
    # Use latest completed year instead.
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
        f"&user=caslas"
    )

def _power_climatology_url(lat, lon):
    return (
        f"https://power.larc.nasa.gov/api/temporal/climatology/point"
        f"?start=1991&end=2020"
        f"&latitude={lat}&longitude={lon}"
        f"&community=sb"
        f"&parameters=T2M,RH2M,WS10M,PRECTOTCORR"
        f"&format=json"
        f"&user=caslas"
    )

def get_monthly_fwi_xclim(
    lat,
    lon,
    year=None,
    ffmc_init=85.0,
    dmc_init=6.0,
    dc_init=15.0,
):
    year = _safe_power_year(year)
    key = (round(lat, 4), round(lon, 4), year)

    if key in monthly_fwi_cache:
        return monthly_fwi_cache[key]

    keys = [f"{year}{month:02d}" for month in range(1, 13)]

    tas_vals = [None] * 12
    hurs_vals = [None] * 12
    wind_vals = [None] * 12
    pr_totals = [None] * 12

    # Try selected/latest-safe year first
    try:
        resp = requests.get(_power_monthly_url(lat, lon, year), timeout=20)
        resp.raise_for_status()
        data_json = resp.json()
        params = data_json["properties"]["parameter"]

        def safe_get(param, k):
            return params.get(param, {}).get(k, None)

        tas_vals = [safe_get("T2M", k) for k in keys]
        hurs_vals = [safe_get("RH2M", k) for k in keys]
        wind_vals = [safe_get("WS10M", k) for k in keys]
        pr_totals = [safe_get("PRECTOTCORR", k) for k in keys]

    except requests.RequestException:
        # Keep Nones and fall through to climatology
        pass

    # Fill missing values from climatology
    try:
        missing_months = [i for i, v in enumerate(tas_vals) if v is None]
        if missing_months:
            resp_clim = requests.get(_power_climatology_url(lat, lon), timeout=20)
            resp_clim.raise_for_status()
            data_clim = resp_clim.json()
            params_clim = data_clim["properties"]["parameter"]

            for i in missing_months:
                month_key = f"{i + 1:02d}"
                tas_vals[i] = params_clim["T2M"][month_key]
                hurs_vals[i] = params_clim["RH2M"][month_key]
                wind_vals[i] = params_clim["WS10M"][month_key]
                pr_totals[i] = params_clim["PRECTOTCORR"][month_key]
    except requests.RequestException as e:
        raise RuntimeError(f"Unable to retrieve monthly climate data for ({lat}, {lon}).") from e

    times = pd.date_range(start=f"{year}-01-01", periods=12, freq="MS")
    days_in_month = times.days_in_month.values

    pr_daily_vals = np.array(pr_totals, dtype=float) / days_in_month
    wind_kmh_vals = np.array(wind_vals, dtype=float) * 3.6  # m/s -> km/h

    da_tas = to_da(np.array(tas_vals, dtype=float), times, "tas", "°C")
    da_hurs = to_da(np.array(hurs_vals, dtype=float), times, "hurs", "%")
    da_wind = to_da(wind_kmh_vals, times, "sfcWind", "km/h")
    da_pr = to_da(pr_daily_vals, times, "pr", "mm d-1")

    da_ffmc0 = xr.DataArray(ffmc_init, name="ffmc0", attrs={"units": "1"})
    da_dmc0 = xr.DataArray(dmc_init, name="dmc0", attrs={"units": "mm"})
    da_dc0 = xr.DataArray(dc_init, name="dc0", attrs={"units": "mm"})
    da_lat = xr.DataArray(lat, name="lat", attrs={"units": "degrees_north"})

    (_, _, _, _, _, fire_weather_index) = cffwis_indices(
        tas=da_tas,
        pr=da_pr,
        sfcWind=da_wind,
        hurs=da_hurs,
        lat=da_lat,
        ffmc0=da_ffmc0,
        dmc0=da_dmc0,
        dc0=da_dc0,
    )

    monthly_fwi = fire_weather_index.values.tolist()
    monthly_fwi_cache[key] = monthly_fwi
    return monthly_fwi


# -------------------------------------------------------------------
# CATEGORIES: FWI + FRI + FSI (config driven)
# -------------------------------------------------------------------
def categorize_fwi(fwi: float) -> str:
    """
    Context-adjusted FWI bands for Cox’s Bazar-type climate.

    Values/thresholds are pulled from config.py so they are easy to tune.
    """
    if fwi < FWI_LOW_MAX:
        return "Low fire danger"
    elif fwi < FWI_MODERATE_MAX:
        return "Moderate fire danger"
    elif fwi < FWI_HIGH_MAX:
        return "High fire danger"
    else:
        return "Severe fire danger"


def categorize_fri(fri: float) -> str:
    if fri < FRI_LOW_MAX:
        return "Low risk"
    elif fri < FRI_MODERATE_MAX:
        return "Moderate risk"
    elif fri < FRI_HIGH_MAX:
        return "High risk"
    else:
        return "Extreme risk"


def classify_fsi(fsi: float) -> str:
    if fsi >= FSI_URGENT_THRESHOLD:
        return "Urgent"
    elif fsi >= FSI_HIGH_THRESHOLD:
        return "High"
    else:
        return "Moderate"

# -------------------------------------------------------------------
# NARRATIVE HELPERS
# -------------------------------------------------------------------
def explain_fri_value(fri_value: int) -> str:
    cls = categorize_fri(fri_value)
    if cls == "Low risk":
        return (
            f"{fri_value} falls in the LOW risk band: fire outbreaks are less likely, "
            "but basic preparedness (clear escape routes, functioning fire points) "
            "should still be maintained."
        )
    elif cls == "Moderate risk":
        return (
            f"{fri_value} is a MODERATE risk: conditions allow fires to spread if they start. "
            "Extra attention to cooking practices, safe LPG handling and rapid detection is advised."
        )
    elif cls == "High risk":
        return (
            f"{fri_value} is a HIGH risk: a single fire could spread quickly between shelters. "
            "Readiness of volunteers, clear access for responders and targeted risk reduction "
            "activities should be prioritised."
        )
    else:  # Extreme
        return (
            f"{fri_value} is an EXTREME risk: even small ignitions can become large incidents. "
            "Non-essential fire-prone activities should be reduced and contingency plans "
            "reviewed with the community."
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

    else:
        return (
            f"{fwi_value} indicates SEVERE fire-weather danger: very hot, dry and/or windy "
            "weather means any fire can spread rapidly and become difficult to control."
        )


def build_current_risk_narrative(selected_camp: str, df_fri: pd.DataFrame):
    from dash import html

    total = len(df_fri)
    row = df_fri.loc[df_fri["CampName"] == selected_camp].iloc[0]
    fri = int(row["FRI"])
    cls = row["FRI_Class"]

    df_sorted = df_fri.sort_values("FRI", ascending=False).reset_index(drop=True)
    rank = int(df_sorted.index[df_sorted["CampName"] == selected_camp][0]) + 1
    if total > 1:
        percentile = round(100 * (total - rank) / (total - 1))
    else:
        percentile = 0

    counts = df_fri["FRI_Class"].value_counts().to_dict()
    extreme = counts.get("Extreme risk", 0)
    high = counts.get("High risk", 0)
    moderate = counts.get("Moderate risk", 0)
    low = counts.get("Low risk", 0)

    return html.Div(
        [
            html.H5("Current Fire Risk Summary", style={"fontWeight": "bold"}),
            html.P(
                f"Today, **{selected_camp}** has a Fire Risk Index (FRI) of **{fri}** "
                f"({cls}), ranking **{rank}** out of **{total}** camps "
                f"(around the top {percentile}%).",
                style={"fontSize": "14px"},
            ),
            html.P(
                explain_fri_value(fri),
                style={"fontSize": "14px"},
            ),
            html.P(
                f"Across all sites today: {extreme} camp(s) are in the *Extreme* band, "
                f"{high} in *High*, {moderate} in *Moderate* and {low} in *Low* risk. "
                "This helps prioritise where preparedness and response capacity should "
                "be focused.",
                style={"fontSize": "14px"},
            ),
        ]
    )


def build_current_weather_narrative(
    selected_camp: str, df_fwi: pd.DataFrame
):
    from dash import html

    total = len(df_fwi)
    row = df_fwi.loc[df_fwi["CampName"] == selected_camp].iloc[0]
    fwi = int(row["FWI"])
    cls = categorize_fwi(fwi)

    df_sorted = df_fwi.sort_values("FWI", ascending=False).reset_index(drop=True)
    rank = int(df_sorted.index[df_sorted["CampName"] == selected_camp][0]) + 1
    if total > 1:
        percentile = round(100 * (total - rank) / (total - 1))
    else:
        percentile = 0

    df_fwi["Risk"] = df_fwi["FWI"].apply(categorize_fwi)
    counts = df_fwi["Risk"].value_counts().to_dict()
    low = counts.get("Low fire danger", 0)
    moderate = counts.get("Moderate fire danger", 0)
    severe = counts.get("Severe fire danger", 0)

    return html.Div(
        [
            html.H5("Current Fire Weather Summary", style={"fontWeight": "bold"}),
            html.P(
                f"Today, **{selected_camp}** has a Fire Weather Index (FWI) of **{fwi}** "
                f"({cls}), ranking **{rank}** out of **{total}** camps "
                f"(around the top {percentile}%).",
                style={"fontSize": "14px"},
            ),
            html.P(
                explain_fwi_value(fwi),
                style={"fontSize": "14px"},
            ),
            html.P(
                f"Across all sites: {severe} camp(s) are facing *Severe* fire-weather danger, "
                f"{moderate} are *Moderate* and {low} are *Low*. "
                "These conditions do not cause fires by themselves, but they strongly affect "
                "how quickly a fire can grow once it starts.",
                style={"fontSize": "14px"},
            ),
        ]
    )


def build_monthly_risk_narrative(
    selected_camp: str, df_month: pd.DataFrame, value_col: str, index_name: str
):
    from dash import html

    peak_row = df_month.loc[df_month[value_col].idxmax()]
    low_row = df_month.loc[df_month[value_col].idxmin()]

    high_like = df_month[
        df_month["risk"].isin(
            ["High risk", "Extreme risk", "Severe fire danger"]
        )
    ]
    moderate_like = df_month[
        df_month["risk"].isin(["Moderate risk", "Moderate fire danger"])
    ]

    return html.Div(
        [
            html.H5(f"Monthly {index_name}", style={"fontWeight": "bold"}),
            html.P(
                f"For **{selected_camp}**, the highest monthly {index_name} occurs in "
                f"**{peak_row['month']}** (value **{int(peak_row[value_col])}**), while "
                f"the lowest occurs in **{low_row['month']}** "
                f"(**{int(low_row[value_col])}**).",
                style={"fontSize": "14px"},
            ),
            html.P(
                f"Over the year, {len(high_like)} month(s) reach High/Severe bands and "
                f"{len(moderate_like)} are in a Moderate band. These periods indicate when "
                "extra preparedness (community messaging, drills, equipment checks) "
                "is most important.",
                style={"fontSize": "14px"},
            ),
        ]
    )


def build_forecast_narrative(
    selected_camp: str, df_fc: pd.DataFrame, value_col: str, index_name: str
):
    from dash import html

    counts = df_fc["Risk"].value_counts().to_dict()
    low = counts.get("Low risk", 0) + counts.get("Low fire danger", 0)
    moderate = counts.get("Moderate risk", 0) + counts.get(
        "Moderate fire danger", 0
    )
    high = counts.get("High risk", 0)
    extreme = counts.get("Extreme risk", 0)
    severe = counts.get("Severe fire danger", 0)

    high_like = df_fc[
        df_fc["Risk"].isin(
            ["High risk", "Extreme risk", "Severe fire danger"]
        )
    ]
    if not high_like.empty:
        first_peak = high_like.iloc[0]
        first_peak_text = (
            f"The first high-danger day is **{first_peak['Date']}** "
            f"({index_name} ≈ **{int(first_peak[value_col])}**, {first_peak['Risk']})."
        )
    else:
        first_peak_text = "No High/Severe days are forecast in the next 14 days."

    return html.Div(
        [
            html.H5(f"14-Day {index_name} Forecast", style={"fontWeight": "bold"}),
            html.P(
                f"Over the next 14 days in **{selected_camp}**, the forecast shows: "
                f"{extreme or severe} day(s) in the highest danger band, "
                f"{high} in High, {moderate} in Moderate and {low} in Low.",
                style={"fontSize": "14px"},
            ),
            html.P(
                first_peak_text,
                style={"fontSize": "14px"},
            ),
            html.P(
                "Use this outlook to plan staff presence, drills, messaging and checks on "
                "critical equipment in the days where danger is highest.",
                style={"fontSize": "14px"},
            ),
        ]
    )
def get_openmeteo_14day_weather(lat, lon, start_date=None, horizon=14):
    """
    Fetch 14-day forecast weather from Open-Meteo.

    Returns a dataframe with:
    date, temp, rh, wind, wind_dir_deg, wind_dir_label, precip
    using 13:00 local values for temp/rh/wind/wind direction and
    daily precipitation_sum for rainfall.
    """
    if start_date is None:
        start_date = date.today() + timedelta(days=1)

    end_date = start_date + timedelta(days=horizon - 1)

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
        f"&hourly=temperature_2m,relativehumidity_2m,windspeed_10m,winddirection_10m"
        f"&daily=precipitation_sum"
        f"&timezone=auto"
    )

    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        js = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[WARN] 14-day Open-Meteo forecast failed: {repr(e)}")
        return pd.DataFrame(
            columns=["date", "temp", "rh", "wind", "wind_dir_deg", "wind_dir_label", "precip"]
        )

    hourly = js.get("hourly", {})
    daily = js.get("daily", {})

    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    rhs = hourly.get("relativehumidity_2m", [])
    winds = hourly.get("windspeed_10m", [])
    wind_dirs = hourly.get("winddirection_10m", [])

    daily_times = daily.get("time", [])
    daily_precip = daily.get("precipitation_sum", [])

    precip_map = {
        d: p for d, p in zip(daily_times, daily_precip)
    }

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
            # fallback to daily averages from available hourly values for that date
            idxs = [i for i, t in enumerate(times) if t.startswith(iso_date)]
            if idxs:
                temp_vals = [temps[i] for i in idxs if i < len(temps)]
                rh_vals = [rhs[i] for i in idxs if i < len(rhs)]
                wind_vals = [winds[i] for i in idxs if i < len(winds)]
                dir_vals = [wind_dirs[i] for i in idxs if i < len(wind_dirs)]

                temp = max(temp_vals) if temp_vals else None
                rh = sum(rh_vals) / len(rh_vals) if rh_vals else None
                wind = sum(wind_vals) / len(wind_vals) if wind_vals else None
                wind_dir_deg = sum(dir_vals) / len(dir_vals) if dir_vals else None
            else:
                temp = None
                rh = None
                wind = None
                wind_dir_deg = None

        rows.append(
            {
                "date": iso_date,
                "temp": round(float(temp), 1) if temp is not None else np.nan,
                "rh": round(float(rh), 1) if rh is not None else np.nan,
                "wind": round(float(wind), 1) if wind is not None else np.nan,
                "wind_dir_deg": round(float(wind_dir_deg), 1) if wind_dir_deg is not None else np.nan,
                "wind_dir_label": degrees_to_compass(wind_dir_deg),
                "precip": round(float(precip_map.get(iso_date, 0) or 0), 1),
            }
        )

    return pd.DataFrame(rows)


def compute_fwi_sequence_xclim(weather_df, lat, ffmc0=85.0, dmc0=6.0, dc0=15.0):
    """
    Compute a stateful multi-day FWI sequence using xclim CFFWIS.
    """
    if weather_df.empty:
        return weather_df.copy()

    times = pd.to_datetime(weather_df["date"])

    da_tas = xr.DataArray(
        weather_df["temp"].astype(float).to_numpy(),
        dims=("time",),
        coords={"time": times},
        name="tas",
        attrs={"units": "degC"},
    )

    da_hurs = xr.DataArray(
        weather_df["rh"].astype(float).to_numpy(),
        dims=("time",),
        coords={"time": times},
        name="hurs",
        attrs={"units": "%"},
    )

    da_wind = xr.DataArray(
        weather_df["wind"].astype(float).to_numpy(),
        dims=("time",),
        coords={"time": times},
        name="sfcWind",
        attrs={"units": "km/h"},
    )

    da_pr = xr.DataArray(
        weather_df["precip"].astype(float).to_numpy(),
        dims=("time",),
        coords={"time": times},
        name="pr",
        attrs={"units": "mm/d"},
    )

    da_lat = xr.DataArray(lat, attrs={"units": "degrees_north"})
    da_ffmc0 = xr.DataArray(ffmc0, attrs={"units": ""})
    da_dmc0 = xr.DataArray(dmc0, attrs={"units": ""})
    da_dc0 = xr.DataArray(dc0, attrs={"units": ""})

    ffmc, dmc, dc, isi, bui, fwi = cffwis_indices(
        tas=da_tas,
        pr=da_pr,
        sfcWind=da_wind,
        hurs=da_hurs,
        lat=da_lat,
        ffmc0=da_ffmc0,
        dmc0=da_dmc0,
        dc0=da_dc0,
    )

    out = weather_df.copy()
    out["FFMC"] = np.round(ffmc.values, 1)
    out["DMC"] = np.round(dmc.values, 1)
    out["DC"] = np.round(dc.values, 1)
    out["ISI"] = np.round(isi.values, 1)
    out["BUI"] = np.round(bui.values, 1)
    out["FWI"] = np.round(fwi.values, 1)
    out["FWI_Risk"] = out["FWI"].apply(categorize_fwi)

    return out


def apply_dynamic_fsi_adjustment(forecast_df, base_fsi):
    """
    Create a short-term weather-stressed susceptibility adjustment.

    This is a practical heuristic, not a formally validated FSI model.
    It nudges base susceptibility up/down using:
    - consecutive dry days
    - strong wind
    - low humidity
    - meaningful rainfall relief
    """
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

        if precip < 1.0:
            dryness_streak += 1
        else:
            dryness_streak = 0

        dryness_bonus = min(dryness_streak * 1.5, 8.0)
        wind_bonus = min(max(wind - 20.0, 0) * 0.2, 5.0)
        humidity_bonus = min(max(45.0 - rh, 0) * 0.15, 5.0)
        rain_penalty = min(precip * 0.8, 6.0)

        adjusted_fsi = base_fsi + dryness_bonus + wind_bonus + humidity_bonus - rain_penalty
        adjusted_fsi = max(0, min(100, round(adjusted_fsi, 1)))

        adjusted_fsis.append(adjusted_fsi)

    out["Adjusted_FSI"] = adjusted_fsis
    out["FRI"] = np.round(out["Adjusted_FSI"] * (1 + out["FWI"] / 100.0), 1)
    out["FRI_Risk"] = out["FRI"].apply(categorize_fri)

    return out


def get_14day_fire_forecast(lat, lon, base_fsi, ffmc0=85.0, dmc0=6.0, dc0=15.0):
    """
    Full 14-day projected fire risk forecast:
    - fetch forecast weather
    - compute stateful FWI sequence
    - apply dynamic short-term FSI adjustment
    - compute FRI
    """
    weather_df = get_openmeteo_14day_weather(lat, lon)

    if weather_df.empty:
        return pd.DataFrame(
            columns=[
                "date", "Date", "temp", "rh", "wind", "wind_dir_deg", "wind_dir_label",
                "precip", "FWI", "FWI_Risk", "Adjusted_FSI", "FRI", "FRI_Risk"
            ]
        )

    fwi_df = compute_fwi_sequence_xclim(
        weather_df, lat=lat, ffmc0=ffmc0, dmc0=dmc0, dc0=dc0
    )
    out = apply_dynamic_fsi_adjustment(fwi_df, base_fsi=float(base_fsi))
    out["Date"] = pd.to_datetime(out["date"]).dt.strftime("%b %d")

    return out