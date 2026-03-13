# app.py
import os
import math
from datetime import date, timedelta
import dash_leaflet as dl
from dash import html, dcc
import dash_bootstrap_components as dbc

from fire_risk.legacy.data import equipment_df

import numpy as np
import pandas as pd
import dash
from dash import html, dcc, dash_table, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
pio.templates.default = "plotly_white"
from pathlib import Path
OUTLOOK_YEAR = date.today().year
OUTLOOK_LABEL = f"Seasonal Outlook {OUTLOOK_YEAR}"

from fire_risk.legacy.data import (
    cleaned_data,
    camp_summary,
    response_details,
    geojson_data,
    block_geojson,
    equipment_df,
)
from fire_risk.legacy.fwi_fri import (
    get_weather_noon,
    get_fwi_xclim,
    get_monthly_fwi_xclim,
    get_14day_fire_forecast,
    categorize_fwi,
    categorize_fri,
    classify_fsi,
    build_current_risk_narrative,
    build_current_weather_narrative,
    build_monthly_risk_narrative,
    build_forecast_narrative,
)
from fire_risk.legacy.layouts import (
    navbar,
    site_level_layout,
    block_level_layout,
    overview_layout,
    about_layout,
    section_card,
    FA_URL,
)

# -------------------------------------------------------------------
# INDICATOR DEFINITIONS
# -------------------------------------------------------------------

APP_BASE_DIR = Path(__file__).resolve().parents[2]
DEFINITIONS_FILE = APP_BASE_DIR / "fire_indicator_definitions.csv"

print("Looking for definitions file at:", DEFINITIONS_FILE)
print("File exists:", DEFINITIONS_FILE.exists())


def load_indicator_definitions_df():
    print("Looking for definitions file at:", DEFINITIONS_FILE)
    print("File exists:", DEFINITIONS_FILE.exists())

    try:
        df = pd.read_csv(DEFINITIONS_FILE, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(DEFINITIONS_FILE, encoding="latin1")
    except Exception as e:
        print("ERROR reading definitions CSV:", repr(e))
        return pd.DataFrame(
            columns=["code", "section", "parent_code", "question", "description", "rationale", "status"]
        )

    print("Definitions CSV loaded successfully.")
    print("Original columns:", list(df.columns))
    print("Row count before cleaning:", len(df))

    # normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    print("Normalized columns:", list(df.columns))

    # expected columns
    expected = ["code", "section", "parent_code", "question", "description", "rationale", "status"]
    for col in expected:
        if col not in df.columns:
            df[col] = ""

    # normalize key fields
    for col in ["code", "section", "parent_code", "question", "description", "rationale", "status"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # keep rows that actually have a code
    df = df[df["code"] != ""].copy()

    print("Row count after keeping nonblank code:", len(df))
    print("Sample codes:", df["code"].head(10).tolist())

    return df

INDICATOR_DEFINITIONS_DF = load_indicator_definitions_df()

# -------------------------------------------------------------------
# INDICATOR COLUMN MAPPINGS
# -------------------------------------------------------------------
INDICATOR_GROUPS = {
    "ENV_001": ["ENV_001"],
    "ENV_002": ["ENV_002"],
    "ENV_003": ["ENV_003a", "ENV_003b"],
    "ENV_004": ["ENV_004"],

    "FUEL_001": ["FUEL_001"],
    "FUEL_002": ["FUEL_002a", "FUEL_002b"],
    "FUEL_003": ["FUEL_003a", "FUEL_003b"],

    "BEH_001": ["BEH_001a", "BEH_001b"],
    "BEH_002": ["BEH_002"],
    "BEH_003": ["BEH_003"],
    "BEH_004": ["BEH_004"],
    "BEH_005": ["BEH_005"],
    "BEH_006": ["BEH_006a", "BEH_006b"],
    "BEH_007": ["BEH_007"],
    "BEH_008": ["BEH_008"],

    "RES_001": ["RES_001a", "RES_001b", "RES_001c", "RES_001d", "RES_001e", "RES_001f", "RES_001g"],
    "RES_002": ["RES_002"],
    "RES_003": ["RES_003a", "RES_003b", "RES_003c", "RES_003d"],
    "RES_005": ["RES_005a", "RES_005b", "RES_005c"],
}

def build_indicator_score_table(selected_df, full_df):
    rows = []

    for indicator, raw_cols in INDICATOR_GROUPS.items():
        existing_selected = [c for c in raw_cols if c in selected_df.columns]
        existing_full = [c for c in raw_cols if c in full_df.columns]

        if not existing_selected or not existing_full:
            continue

        # score for selected block
        selected_vals = (
            selected_df[existing_selected]
            .apply(pd.to_numeric, errors="coerce")
        )

        # overall benchmark mean
        full_vals = (
            full_df[existing_full]
            .apply(pd.to_numeric, errors="coerce")
        )

        # row-level mean across sub-indicators, then overall mean
        selected_score = selected_vals.mean(axis=1, skipna=True).dropna()
        full_score = full_vals.mean(axis=1, skipna=True).dropna()

        if selected_score.empty:
            continue

        rows.append(
            {
                "Indicator": indicator,
                "Score": round(float(selected_score.mean()), 2),
                "Mean": round(float(full_score.mean()), 6) if not full_score.empty else None,
            }
        )

    out = pd.DataFrame(rows)

    if out.empty:
        return out

    out["Rank"] = out["Score"].rank(method="dense", ascending=False).astype(int)
    out = out.sort_values("Indicator").reset_index(drop=True)

    return out[["Indicator", "Score", "Rank", "Mean"]]

def classify_dimension_score(score):
    if score >= 75:
        return "Very High"
    elif score >= 60:
        return "High"
    elif score >= 40:
        return "Moderate"
    else:
        return "Low"


def build_block_advisory_narrative(environment_score, fuel_score, behaviour_score, response_score):
    env_level = classify_dimension_score(environment_score)
    fuel_level = classify_dimension_score(fuel_score)
    beh_level = classify_dimension_score(behaviour_score)
    res_level = classify_dimension_score(response_score)

    advice = []

    # Environment
    if environment_score >= 60:
        advice.append(
            f"Environment risk is {env_level.lower()} ({environment_score}). "
            "Priority actions should include improving spacing around shelters where feasible, "
            "keeping access paths clear for emergency movement, reducing congestion around shared facilities, "
            "and strengthening basic site-level firebreak arrangements."
        )
    elif environment_score >= 40:
        advice.append(
            f"Environment risk is {env_level.lower()} ({environment_score}). "
            "Site planning controls should be maintained, with attention to blocked access routes, "
            "encroachment between shelters, and localized congestion that could accelerate fire spread."
        )
    else:
        advice.append(
            f"Environment risk is {env_level.lower()} ({environment_score}). "
            "Current site conditions appear relatively better controlled, but routine monitoring of spacing, "
            "accessibility, and exposure points should continue."
        )

    # Fuel
    if fuel_score >= 60:
        advice.append(
            f"Fuel risk is {fuel_level.lower()} ({fuel_score}). "
            "This suggests a high presence or poor management of combustible materials. "
            "Actions should focus on reducing dry waste accumulation, improving safe storage of fuel and flammables, "
            "keeping cooking areas clear, and removing unnecessary burnable materials from around shelters."
        )
    elif fuel_score >= 40:
        advice.append(
            f"Fuel risk is {fuel_level.lower()} ({fuel_score}). "
            "Targeted action is needed to improve housekeeping, waste removal, and safer storage of combustible items."
        )
    else:
        advice.append(
            f"Fuel risk is {fuel_level.lower()} ({fuel_score}). "
            "Fuel load appears comparatively lower, but regular waste management and safe storage practices should be sustained."
        )

    # Behaviour
    if behaviour_score >= 60:
        advice.append(
            f"Behaviour risk is {beh_level.lower()} ({behaviour_score}). "
            "Community fire prevention messaging should be intensified. "
            "Key priorities include safer cooking behaviour, reducing open flames inside or near shelters, "
            "improving child supervision around ignition sources, and reinforcing reporting of unsafe practices."
        )
    elif behaviour_score >= 40:
        advice.append(
            f"Behaviour risk is {beh_level.lower()} ({behaviour_score}). "
            "Continued awareness activities are needed, especially around cooking safety, flame use, and day-to-day fire prevention habits."
        )
    else:
        advice.append(
            f"Behaviour risk is {beh_level.lower()} ({behaviour_score}). "
            "Behavioural risk appears relatively lower, though routine awareness and reinforcement should continue."
        )

    # Response
    if response_score >= 60:
        advice.append(
            f"Response risk is {res_level.lower()} ({response_score}). "
            "Response capacity needs urgent strengthening. "
            "Recommended measures include improving access to extinguishing materials, refresher training for community volunteers, "
            "clear escalation and reporting arrangements, and ensuring rapid access for first responders."
        )
    elif response_score >= 40:
        advice.append(
            f"Response risk is {res_level.lower()} ({response_score}). "
            "Preparedness systems should be reinforced through targeted checks on equipment, volunteer readiness, and communication pathways."
        )
    else:
        advice.append(
            f"Response risk is {res_level.lower()} ({response_score}). "
            "Response arrangements appear relatively stronger, but equipment checks, drills, and readiness reviews should continue."
        )

    # Overall emphasis
    highest_dim = max(
        {
            "Environment": environment_score,
            "Fuel": fuel_score,
            "Behaviour": behaviour_score,
            "Response": response_score,
        },
        key=lambda k: {
            "Environment": environment_score,
            "Fuel": fuel_score,
            "Behaviour": behaviour_score,
            "Response": response_score,
        }[k],
    )

    overall = (
        f"The highest contributing susceptibility dimension for this block is {highest_dim}. "
        "Risk reduction efforts should prioritize this area first, while maintaining integrated action across all four dimensions."
    )

    return advice, overall
def build_fire_risk_outlook_calendar(df_fc, value_col="FRI", risk_col="FRI_Risk", title="14-Day Fire Risk Outlook Calendar"):
    if df_fc.empty:
        return go.Figure()

    cal_df = df_fc.copy()
    cal_df["DayLabel"] = cal_df["Date"]
    cal_df["Row"] = ["Outlook"] * len(cal_df)

    risk_score_map = {
        "Low risk": 1,
        "Moderate risk": 2,
        "High risk": 3,
        "Extreme risk": 4,
        "Low fire danger": 1,
        "Moderate fire danger": 2,
        "High fire danger": 3,
        "Severe fire danger": 4,
    }

    cal_df["RiskScore"] = cal_df[risk_col].map(risk_score_map).fillna(0)

    fig = go.Figure(
        data=go.Heatmap(
            z=[cal_df["RiskScore"].tolist()],
            x=cal_df["DayLabel"].tolist(),
            y=["Outlook"],
            text=[
                [
                    f"{row['Date']}<br>"
                    f"{value_col}: {row[value_col]}<br>"
                    f"{risk_col}: {row[risk_col]}"
                    for _, row in cal_df.iterrows()
                ]
            ],
            hoverinfo="text",
            colorscale=[
                [0.00, "#22c55e"],   # green
                [0.25, "#facc15"],   # yellow
                [0.50, "#f97316"],   # orange
                [0.75, "#dc2626"],   # red
                [1.00, "#7e22ce"],   # purple
            ],
            zmin=1,
            zmax=4,
            showscale=False,
        )
    )

    fig.update_layout(
        title=title,
        height=180,
        margin=dict(l=20, r=20, t=50, b=20),
        xaxis=dict(title="", side="top"),
        yaxis=dict(title="", showticklabels=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    return fig

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def build_monthly_outlook_df(lat, lon, base_fsi, year=2026):
    """
    Seasonal monthly outlook for a full year.
    Uses monthly FWI climatology/series and applies block FSI to derive FRI.
    """
    monthly_fwi = get_monthly_fwi_xclim(lat, lon, year)

    df = pd.DataFrame({
        "MonthNum": list(range(1, 13)),
        "Month": MONTH_LABELS,
        "FWI": monthly_fwi,
    })

    df["FWI"] = (
        pd.to_numeric(df["FWI"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
        .round(1)
    )

    df["FRI"] = (float(base_fsi) * (1 + df["FWI"] / 100.0)).round(1)

    df["FWI_Risk"] = df["FWI"].apply(categorize_fwi)
    df["FRI_Risk"] = df["FRI"].apply(categorize_fri)

    return df


def build_monthly_outlook_heatmap(df_monthly, value_col, risk_col, title):
    """
    One-row monthly heatmap for either FWI or FRI.
    """
    if df_monthly.empty:
        return go.Figure()

    risk_score_map = {
        "Low risk": 1,
        "Moderate risk": 2,
        "High risk": 3,
        "Extreme risk": 4,
        "Low fire danger": 1,
        "Moderate fire danger": 2,
        "High fire danger": 3,
        "Severe fire danger": 4,
    }

    z_vals = [df_monthly[risk_col].map(risk_score_map).fillna(0).tolist()]
    text_vals = [[
        f"{row['Month']} {value_col}: {row[value_col]}<br>{risk_col}: {row[risk_col]}"
        for _, row in df_monthly.iterrows()
    ]]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_vals,
            x=df_monthly["Month"].tolist(),
            y=[value_col],
            text=text_vals,
            hoverinfo="text",
            colorscale=[
                [0.00, "#22c55e"],   # green
                [0.25, "#facc15"],   # yellow
                [0.50, "#f97316"],   # orange
                [0.75, "#dc2626"],   # red
                [1.00, "#7e22ce"],   # purple
            ],
            zmin=1,
            zmax=4,
            showscale=False,
        )
    )

    fig.update_layout(
        title=title,
        height=170,
        margin=dict(l=20, r=20, t=45, b=20),
        xaxis=dict(title="", side="top"),
        yaxis=dict(title="", showticklabels=True),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    return fig


def build_monthly_outlook_narrative(block_name, df_monthly, year=2026):
    """
    Narrative summary for the seasonal outlook.
    """
    if df_monthly.empty:
        return html.P("No seasonal outlook data available.")

    peak_fwi = df_monthly.loc[df_monthly["FWI"].idxmax()]
    peak_fri = df_monthly.loc[df_monthly["FRI"].idxmax()]

    high_fwi_months = df_monthly[
        df_monthly["FWI_Risk"].isin(["High fire danger", "Severe fire danger"])
    ]["Month"].tolist()

    high_fri_months = df_monthly[
        df_monthly["FRI_Risk"].isin(["High risk", "Extreme risk"])
    ]["Month"].tolist()

    return html.Div(
        [
            html.H5(f"Seasonal Outlook Summary ({year})", style={"fontWeight": "bold"}),
            html.P(
                f"For Block {block_name}, the highest projected Fire Weather Index (FWI) is expected in "
                f"{peak_fwi['Month']} ({peak_fwi['FWI']}, {peak_fwi['FWI_Risk']}).",
                style={"fontSize": "14px"},
            ),
            html.P(
                f"The highest projected Fire Risk Index (FRI) is expected in "
                f"{peak_fri['Month']} ({peak_fri['FRI']}, {peak_fri['FRI_Risk']}).",
                style={"fontSize": "14px"},
            ),
            html.P(
                f"Months with elevated fire-weather concern: "
                f"{', '.join(high_fwi_months) if high_fwi_months else 'None'}.",
                style={"fontSize": "14px"},
            ),
            html.P(
                f"Months with elevated operational fire-risk concern: "
                f"{', '.join(high_fri_months) if high_fri_months else 'None'}.",
                style={"fontSize": "14px"},
            ),
            html.P(
                "Use this seasonal view for preparedness planning, awareness campaigns, equipment checks, "
                "and scheduling of prevention activities ahead of higher-risk months.",
                style={"fontSize": "14px"},
            ),
        ]
    )
# -------------------------------------------------------------------
# DASH APP
# -------------------------------------------------------------------
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, FA_URL])
app.title = "Fire Risk Analysis - Site-Level"
app.config.suppress_callback_exceptions = True

app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        navbar,
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle("Indicator Definitions")),
                dbc.ModalBody(id="indicator-definition-content"),
                dbc.ModalFooter(
                    dbc.Button("Close", id="close-indicator-modal", n_clicks=0)
                ),
            ],
            id="indicator-modal",
            is_open=False,
            size="xl",
            scrollable=True,
        ),

        dbc.Offcanvas(
            [
                html.H4("Action Plan", className="mb-3"),
                html.Div(id="action-plan-content"),
            ],
            id="action-plan-offcanvas",
            title="Action Plan",
            is_open=False,
            placement="start",
            scrollable=True,
            style={"width": "420px"},
        ),
        
                    dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Access and Infrastructure Map")),
                    dbc.ModalBody(
                        [
                            html.Div(id="equipment-summary-cards", className="mb-3"),
                            dl.Map(
                                id="equipment-map",
                                center=[21.2, 92.15],
                                zoom=14,
                                style={"width": "100%", "height": "600px"},
                                children=[
                                    dl.TileLayer(),
                                    dl.LayerGroup(id="equipment-boundary-layer"),
                                    dl.LayerGroup(id="equipment-marker-layer"),
                                ],
                            ),
                        ]
                    ),
                    dbc.ModalFooter(
                        dbc.Button("Close", id="close-equipment-map", n_clicks=0)
                    ),
                ],
                id="equipment-map-modal",
                is_open=False,
                size="xl",
                scrollable=True,
            ),

        html.Hr(
            style={
                "margin": "0",
                "padding": "0",
                "borderTop": "1px solid #ccc",
            }
        ),
        dcc.Tabs(id="fwi-tabs", value="seasonal", style={"display": "none"}),
        html.Div(id="page-content"),
    ]
)

app.validation_layout = html.Div(
    [
        app.layout,
        site_level_layout(),
        block_level_layout(),
        overview_layout(),
        about_layout(),
        html.Button(id="open-action-plan"),
        html.Button(id="indicator-definition-link"),
        html.Div(id="block-page-body"),
        html.Div(id="block-fri-content"),
        html.Div(id="block-fwi-content"),
        html.Div(id="site-fwi-content"),
        html.Div(id="site-fwi-narrative"),
        html.Div(id="site-fri-content"),
        dash_table.DataTable(id="overview-table"),
        dcc.Graph(id="overview-heatmap"),
        html.Div(id="site-details"),
        html.Div(id="fsi-index"),
        html.Div(id="fwi-index"),
        html.Div(id="fri-index"),
        dcc.Graph(id="block-bar-chart"),
        dcc.Graph(id="fire-risk-map"),
        dash_table.DataTable(id="susceptibility-table"),
        html.Iframe(id="windy-iframe"),
        dbc.Collapse(id="contact-collapse"),
        html.Div(id="contact-content"),
        dcc.Graph(id="overview-severity-donut"),
        html.Div(id="overview-kpi-total-camps"),
        html.Div(id="overview-kpi-extreme"),
        html.Div(id="overview-kpi-high"),
        html.Div(id="overview-kpi-avg-fri"),
        html.Div(id="overview-top5"),
        html.Div(id="overview-narrative"),
        html.Button(id="btn-open-equipment-map"),
        html.Button(id="close-equipment-map"),
        html.Div(id="equipment-summary-cards"),
        dl.Map(id="equipment-map"),
        html.Div(id="equipment-boundary-layer"),
        html.Div(id="equipment-marker-layer"),
        html.Div(id="equipment-debug", style={"display": "none"}),
    ]
)


@app.callback(
    Output("equipment-map-title", "children"),
    Input("block-camp-dropdown", "value"),
    Input("block-block-dropdown", "value"),
)
def update_equipment_map_title(camp, block):
    if camp and block:
        return f"Access and Infrastructure Map for Camp {camp}, Block {block}"
    elif camp:
        return f"Access and Infrastructure Map – Camp {camp}"
    return "Access and Infrastructure Map"


@app.callback(
    Output("equipment-debug", "children"),
    Input("btn-open-equipment-map", "n_clicks"),
    Input("close-equipment-map", "n_clicks"),
)
def debug_equipment_clicks(open_clicks, close_clicks):
    return f"open={open_clicks}, close={close_clicks}"

def get_equipment_color(status_group):
    if status_group == "Functional":
        return "green"
    elif status_group == "Non-functional":
        return "red"
    return "orange"


def make_equipment_popup(row):
    return dl.Popup(
        html.Div(
            [
                html.H6(row.get("Type_of facility", "Equipment"), className="mb-1"),
                html.P(f"Camp: {row.get('Camp', 'N/A')}", className="mb-1"),
                html.P(f"Sub-block: {row.get('Sub_block', 'N/A')}", className="mb-1"),
                html.P(f"Majhee Section: {row.get('Majhee_section', 'N/A')}", className="mb-1"),
                html.P(f"Landmark: {row.get('Landmark', 'N/A')}", className="mb-1"),
                html.P(f"Status: {row.get('Overall status', 'N/A')}", className="mb-1"),
                html.P(f"Water Source: {row.get('Source_of water', 'N/A')}", className="mb-1"),
                html.P(f"Distance from water: {row.get('Distance from water source', 'N/A')}", className="mb-1"),
                html.P(f"Material: {row.get('Material', 'N/A')}", className="mb-1"),
                html.P(f"Facility focal: {row.get('Facility focal name', 'N/A')}", className="mb-1"),
                html.P(f"DMU: {row.get('DMU', 'N/A')}", className="mb-1"),
                html.P(f"Warden: {row.get('Warden_name', 'N/A')}", className="mb-1"),
                html.P(f"Remarks: {row.get('Remarks', 'N/A')}", className="mb-1"),
            ],
            style={"minWidth": "260px"}
        ),
        maxWidth=350
    )


# -------------------------------------------------------------------
# BLOCK CAMP → BLOCK DROPDOWN OPTIONS
# -------------------------------------------------------------------
@app.callback(
    [Output("block-block-dropdown", "options"),
     Output("block-block-dropdown", "value")],
    Input("block-camp-dropdown", "value"),
)
def populate_block_dropdown(selected_camp):
    if not selected_camp:
        return [], None

    blocks = (
        cleaned_data.loc[
            cleaned_data["CampName"] == selected_camp, "Block"
        ]
        .dropna()
        .unique()
    )

    block_options = [{"label": b, "value": b} for b in sorted(blocks)]
    return block_options, None


@app.callback(
    Output("equipment-marker-layer", "children"),
    Output("equipment-summary-cards", "children"),
    Output("equipment-map", "center"),
    [Input("block-camp-dropdown", "value"),
     Input("block-block-dropdown", "value")],
)
def update_equipment_map(selected_camp, selected_block):
    dff = equipment_df.copy()

    if selected_camp:
        dff = dff[dff["camp_key"] == str(selected_camp).strip().upper()]

    if selected_block:
        dff = dff[dff["block_key"] == str(selected_block).strip().upper()]

    if dff.empty:
        summary = dbc.Alert("No equipment found for the selected camp/block.", color="warning")
        return [], summary, [21.2, 92.15]

    markers = []
    for _, row in dff.iterrows():
        marker = dl.CircleMarker(
            center=[row["_LATITUDE"], row["_LONGITUDE"]],
            radius=6,
            color=get_equipment_color(row["status_group"]),
            fill=True,
            fillOpacity=0.8,
            children=[make_equipment_popup(row)],
        )
        markers.append(marker)

    total_count = len(dff)
    functional_count = (dff["status_group"] == "Functional").sum()
    non_functional_count = (dff["status_group"] == "Non-functional").sum()

    top_types = dff["Type_of facility"].value_counts().head(3).to_dict()
    top_types_text = " | ".join([f"{k}: {v}" for k, v in top_types.items()]) if top_types else "N/A"

    summary = dbc.Row(
        [
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Total Equipment"), html.H4(total_count)])), md=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Functional"), html.H4(functional_count)])), md=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Non-functional"), html.H4(non_functional_count)])), md=3),
            dbc.Col(dbc.Card(dbc.CardBody([html.H6("Top Types"), html.P(top_types_text)])), md=3),
        ],
        className="g-2"
    )

    center = [dff["_LATITUDE"].mean(), dff["_LONGITUDE"].mean()]
    return markers, summary, center

@app.callback(
    Output("equipment-boundary-layer", "children"),
    [Input("block-camp-dropdown", "value"),
     Input("block-block-dropdown", "value")],
)
def update_equipment_boundaries(selected_camp, selected_block):
    layers = []

    if geojson_data is not None and selected_camp:
        camp_features = [
            feat for feat in geojson_data["features"]
            if str(feat.get("properties", {}).get("CampName", "")).strip().upper()
            == str(selected_camp).strip().upper()
        ]
        if camp_features:
            layers.append(
                dl.GeoJSON(
                    data={"type": "FeatureCollection", "features": camp_features},
                    options={"style": {"color": "#0033A0", "weight": 2, "fillOpacity": 0.05}},
                )
            )

    if block_geojson is not None and selected_camp and selected_block:
        block_features = []
        for feat in block_geojson["features"]:
            props = feat.get("properties", {})
            camp_name = str(props.get("CampName_1") or props.get("CampName") or "").strip().upper()
            block_name = str(props.get("BlockLabel") or props.get("BlockName") or "").strip().upper()

            if (
                camp_name == str(selected_camp).strip().upper()
                and block_name == str(selected_block).strip().upper()
            ):
                block_features.append(feat)

        if block_features:
            layers.append(
                dl.GeoJSON(
                    data={"type": "FeatureCollection", "features": block_features},
                    options={"style": {"color": "red", "weight": 3, "fillOpacity": 0.08}},
                )
            )

    return layers


@app.callback(
    Output("equipment-map-modal", "is_open"),
    Input("btn-open-equipment-map", "n_clicks"),
    Input("close-equipment-map", "n_clicks"),
)
def toggle_equipment_modal(open_clicks, close_clicks):
    open_clicks = open_clicks or 0
    close_clicks = close_clicks or 0
    return open_clicks > close_clicks

# -------------------------------------------------------------------
# NAV FILTERS TOGGLE
# -------------------------------------------------------------------
@app.callback(
    [Output("camp-dropdown-container", "style"), Output("block-filter-container", "style")],
    Input("url", "pathname"),
)
def toggle_nav_filters(pathname):
    base_style = {"alignItems": "center", "justifyContent": "flex-end"}

    if pathname == "/":
        camp_style = {"display": "flex", **base_style}
        block_style = {"display": "none", **base_style}
    elif pathname == "/block":
        camp_style = {"display": "none", **base_style}
        block_style = {"display": "flex", **base_style}
    else:
        camp_style = {"display": "none", **base_style}
        block_style = {"display": "none", **base_style}

    return camp_style, block_style


# -------------------------------------------------------------------
# MULTI-PAGE NAVIGATION
# -------------------------------------------------------------------

@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def display_page(pathname):
    if pathname == "/overview":
        return overview_layout()
    elif pathname == "/about":
        return about_layout()
    elif pathname == "/block":
        return block_level_layout()
    else:
        # default ("/" and anything else)
        return site_level_layout()
    
@app.callback(
    Output("indicator-modal", "is_open"),
    [
        Input("indicator-definition-link", "n_clicks"),
        Input("close-indicator-modal", "n_clicks"),
    ],
    State("indicator-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_indicator_modal(open_clicks, close_clicks, is_open):
    trigger = ctx.triggered_id

    if trigger is None:
        return is_open

    if trigger == "indicator-definition-link" and (open_clicks or 0) > 0:
        return True

    if trigger == "close-indicator-modal" and (close_clicks or 0) > 0:
        return False

    return is_open


@app.callback(
    Output("indicator-definition-content", "children"),
    Input("indicator-definition-link", "n_clicks"),
    prevent_initial_call=True,
)
def populate_definitions(n):
    if INDICATOR_DEFINITIONS_DF.empty:
        return html.Div(
            [
                html.P("The definitions file was found, but no usable rows were loaded."),
                html.P(
                    f"Checked file: {DEFINITIONS_FILE}",
                    style={"fontSize": "12px", "color": "#666"},
                ),
            ]
        )

    df = INDICATOR_DEFINITIONS_DF.copy()

    parent_codes = list(INDICATOR_GROUPS.keys())
    df = df[
        df["code"].isin(parent_codes) |
        df["parent_code"].isin(parent_codes)
    ].copy()

    if df.empty:
        return html.Div(
            [
                html.P("The CSV loaded successfully, but none of its rows matched the dashboard indicator groups."),
                html.P(
                    "Check whether the 'code' and 'parent_code' values in the CSV match indicators like ENV_001, BEH_001, FUEL_002, RES_003.",
                    style={"fontSize": "12px", "color": "#666"},
                ),
            ]
        )

    df = df.sort_values(["section", "parent_code", "code"], na_position="last")

    table = dash_table.DataTable(
        columns=[
            {"name": "Code", "id": "code"},
            {"name": "Section", "id": "section"},
            {"name": "Parent", "id": "parent_code"},
            {"name": "Question", "id": "question"},
            {"name": "Description", "id": "description"},
            {"name": "Rationale", "id": "rationale"},
        ],
        data=df.to_dict("records"),
        style_table={
            "overflowX": "auto",
            "maxHeight": "500px",
            "overflowY": "auto",
        },
        style_cell={
            "textAlign": "left",
            "padding": "8px",
            "fontSize": "12px",
            "whiteSpace": "normal",
            "height": "auto",
            "minWidth": "120px",
            "maxWidth": "300px",
        },
        style_header={
            "fontWeight": "bold",
            "backgroundColor": "#f2f2f2",
        },
        page_size=20,
    )

    return html.Div(
        [
            html.P(
                "Indicator definitions and descriptions",
                style={"fontWeight": "bold", "marginBottom": "10px"},
            ),
            table,
        ]
    )
# -------------------------------------------------------------------
# OVERVIEW FILTER
# -------------------------------------------------------------------
@app.callback(
    [
        Output("overview-table", "data"),
        Output("overview-heatmap", "figure"),
        Output("overview-severity-donut", "figure"),
        Output("overview-kpi-total-camps", "children"),
        Output("overview-kpi-extreme", "children"),
        Output("overview-kpi-high", "children"),
        Output("overview-kpi-avg-fri", "children"),
        Output("overview-top5", "children"),
        Output("overview-narrative", "children"),
    ],
    Input("overview-severity-filter", "value"),
)
def filter_overview(sev):
    dff = camp_summary.copy()

    if sev != "All":
        dff = dff[dff["FRI_Class"] == sev].copy()

    dff["FSI"] = np.ceil(dff["FSI_Calculated"]).astype(int)
    dff["FWI"] = np.ceil(dff["FWI"]).astype(int)
    dff["FRI"] = np.ceil(dff["FRI"]).astype(int)

    dff = dff.sort_values("FRI", ascending=False).reset_index(drop=True)
    dff["Rank"] = dff.index + 1

    table_data = (
        dff[["Rank", "CampName", "FSI", "FWI", "FRI", "FRI_Class"]]
        .rename(columns={
            "CampName": "Camp",
            "FRI_Class": "FRI Severity",
        })
        .to_dict("records")
    )

    total_camps = len(dff)
    extreme_count = int((dff["FRI_Class"] == "Extreme risk").sum()) if not dff.empty else 0
    high_count = int((dff["FRI_Class"] == "High risk").sum()) if not dff.empty else 0
    avg_fri = round(dff["FRI"].mean(), 1) if not dff.empty else 0

    if dff.empty:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            margin={"t": 20, "b": 0, "l": 0, "r": 0},
            annotations=[
                dict(
                    text="No camps match the selected filter.",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
            ],
        )

        empty_donut = go.Figure()
        empty_donut.update_layout(
            margin={"t": 20, "b": 20, "l": 20, "r": 20},
            annotations=[
                dict(
                    text="No data",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
            ],
        )

        return (
            table_data,
            empty_fig,
            empty_donut,
            "0",
            "0",
            "0",
            "0",
            html.P("No camps available under the selected severity filter."),
            html.P("No operational summary available for the current filter."),
        )

    # Map
    map_fig = px.choropleth(
        dff,
        geojson={"type": "FeatureCollection", "features": geojson_data["features"]},
        locations="CampName",
        featureidkey="properties.CampName",
        color="FRI",
        range_color=(0, 100),
        color_continuous_scale="OrRd",
        hover_name="CampName",
        hover_data={
            "FSI": True,
            "FWI": True,
            "FRI": True,
            "CampName": False,
        },
        projection="mercator",
    )
    map_fig.update_geos(fitbounds="locations", visible=False)
    map_fig.update_traces(marker_line_color="black", marker_line_width=0.5)
    map_fig.update_layout(
        margin={"t": 10, "b": 0, "l": 0, "r": 0},
        coloraxis_colorbar=dict(title="FRI"),
    )

    # Severity donut
    sev_counts = (
        dff["FRI_Class"]
        .value_counts()
        .reindex(["Extreme risk", "High risk", "Moderate risk", "Low risk"], fill_value=0)
        .reset_index()
    )
    sev_counts.columns = ["Severity", "Count"]

    donut_fig = px.pie(
        sev_counts,
        names="Severity",
        values="Count",
        hole=0.55,
        color="Severity",
        color_discrete_map={
            "Extreme risk": "#b91c1c",
            "High risk": "#ea580c",
            "Moderate risk": "#facc15",
            "Low risk": "#22c55e",
        },
    )
    donut_fig.update_traces(textposition="inside", textinfo="percent+label")
    donut_fig.update_layout(margin={"t": 0, "b": 0, "l": 0, "r": 0}, showlegend=False)

    # Top 5 camps
    top5 = dff.head(5)
    top5_children = html.Ol(
        [
            html.Li(
                f"{row.CampName} — FRI {row.FRI} ({row.FRI_Class})"
            )
            for _, row in top5.iterrows()
        ],
        style={"paddingLeft": "18px", "fontSize": "14px", "marginBottom": "0"},
    )

    # Narrative
    highest = dff.iloc[0]
    lowest = dff.iloc[-1]

    narrative = html.Div(
        [
            html.P(
                f"There are {total_camps} camps in the current view. "
                f"{extreme_count} camp(s) fall under extreme risk and {high_count} under high risk.",
                style={"fontSize": "14px"},
            ),
            html.P(
                f"The highest-risk camp is {highest['CampName']} with an FRI of {highest['FRI']} "
                f"({highest['FRI_Class']}). The lowest-risk camp in the current view is "
                f"{lowest['CampName']} with an FRI of {lowest['FRI']}.",
                style={"fontSize": "14px"},
            ),
            html.P(
                "Operational attention should focus first on camps in the extreme and high-risk categories, "
                "while maintaining prevention and preparedness measures in moderate-risk camps.",
                style={"fontSize": "14px", "marginBottom": "0"},
            ),
        ]
    )

    return (
        table_data,
        map_fig,
        donut_fig,
        str(total_camps),
        str(extreme_count),
        str(high_count),
        str(avg_fri),
        top5_children,
        narrative,
    )

# -------------------------------------------------------------------
# BLOCK-LEVEL PAGE LAYOUT BUILDER
# -------------------------------------------------------------------
def build_block_level_content(camp_name, block_name):
    """
    Main layout builder for the Block-Level page (for a single camp + block).
    Uses xclim-based FWI everywhere.
    """
    block_data = cleaned_data[
        (cleaned_data["CampName"] == camp_name)
        & (cleaned_data["Block"] == block_name)
    ]

    if block_data.empty:
        from dash import html
        return html.P("No data available for this block.", style={"color": "red"})

    camp_all = cleaned_data[cleaned_data["CampName"] == camp_name]

    from dash import html

    # 1) Assessment date range
    assessment_text = "N/A"
    if "assessment_date" in block_data.columns:
        dates = pd.to_datetime(block_data["assessment_date"], errors="coerce").dropna()
        if not dates.empty:
            min_date = dates.min().date().isoformat()
            max_date = dates.max().date().isoformat()
            assessment_text = min_date if min_date == max_date else f"{min_date} to {max_date}"

    # 2) Site population from ENV_003a column
    population_text = "N/A"
    pop_col = "ENV_003a"
    if pop_col in block_data.columns:
        site_pop = pd.to_numeric(block_data[pop_col], errors="coerce").fillna(0).sum()
        population_text = f"{site_pop:,.0f}"

    # 3) FSI / FWI / FRI for this block
    dims_mean = block_data[["Environment", "Fuel", "Behaviour", "Response"]].mean()
    fsi_value = math.ceil(
        (dims_mean["Environment"] +
         dims_mean["Fuel"] +
         dims_mean["Behaviour"] +
         dims_mean["Response"]) / 4
    )
    fsi_class = classify_fsi(fsi_value)

    env_score = math.ceil(dims_mean["Environment"])
    fuel_score = math.ceil(dims_mean["Fuel"])
    beh_score = math.ceil(dims_mean["Behaviour"])
    res_score = math.ceil(dims_mean["Response"])

    advisory_points, advisory_overall = build_block_advisory_narrative(
        env_score, fuel_score, beh_score, res_score
    )

    lat = block_data["Latitude"].mean()
    lon = block_data["Longitude"].mean()

    today_iso = date.today().isoformat()
    fwi_value = math.ceil(get_fwi_xclim(lat, lon, date_for=today_iso))

    fri_value = math.ceil(fsi_value * (1 + fwi_value / 100))
    fri_severity = categorize_fri(fri_value)

    # 4) Block-level stats within camp
    block_stats = (
        camp_all
        .groupby("Block")[["Environment", "Fuel", "Behaviour", "Response", "Latitude", "Longitude"]]
        .mean()
        .reset_index()
    )

    block_stats["FSI"] = (
        block_stats["Environment"] +
        block_stats["Fuel"] +
        block_stats["Behaviour"] +
        block_stats["Response"]
    ) / 4.0

    block_stats["FRI"] = np.ceil(block_stats["FSI"] * (1 + fwi_value / 100)).astype(int)
    block_stats["FRI_Class"] = block_stats["FRI"].apply(categorize_fri)

    block_stats_sorted = block_stats.sort_values("FRI", ascending=False).reset_index(drop=True)
    rank = int(block_stats_sorted.index[block_stats_sorted["Block"] == block_name][0]) + 1
    total_blocks = len(block_stats_sorted)
    percentile = round(100 * (total_blocks - rank) / (total_blocks - 1)) if total_blocks > 1 else 0

    counts_block = block_stats_sorted["FRI_Class"].value_counts().to_dict()
    b_extreme = counts_block.get("Extreme risk", 0)
    b_high = counts_block.get("High risk", 0)
    b_mod = counts_block.get("Moderate risk", 0)
    b_low = counts_block.get("Low risk", 0)

    # 5) Top row cards
    site_card_body = html.Div(
        [
            html.P([html.Strong("Camp: "), camp_name]),
            html.P([html.Strong("Block: "), block_name]),
            html.P([html.Strong("Assessment date: "), assessment_text]),
            html.P([html.Strong("Site population: "), population_text]),
        ],
        style={"fontSize": "14px"},
    )

    fsi_body = html.Div(
        [
            html.H2(f"{fsi_value} – {fsi_class}", className="mt-1 mb-1"),
            html.P(
                f"(Environment: {math.ceil(dims_mean['Environment'])}, "
                f"Fuel: {math.ceil(dims_mean['Fuel'])}, "
                f"Behaviour: {math.ceil(dims_mean['Behaviour'])}, "
                f"Response: {math.ceil(dims_mean['Response'])})",
                style={"fontSize": "14px", "color": "#555"},
            ),
        ],
        className="text-center",
    )

    w_today = get_weather_noon(lat, lon, today_iso)
    wind_dir_label = w_today.get("wind_dir_label", "N/A")
    wind_dir_deg = w_today.get("wind_dir_deg", None)
    source_status = w_today.get("source_status", "fallback")

    temp_text = f"{w_today['temp']}°C" if w_today["temp"] != "N/A" else "N/A"
    rh_text = f"{w_today['rh']}%" if w_today["rh"] != "N/A" else "N/A"
    wind_text = f"{w_today['wind']} km/h" if w_today["wind"] != "N/A" else "N/A"
    precip_text = f"{w_today['precip']} mm"

    wind_dir_text = (
        f"{wind_dir_label} / {wind_dir_deg}°"
        if wind_dir_deg is not None else wind_dir_label
    )

    weather_details = (
        f"Temp: {temp_text}; "
        f"RH: {rh_text}; "
        f"Wind: {wind_text} ({wind_dir_text}); "
        f"Precip: {precip_text}"
    )
    last_update = f"{today_iso} 13:00 LST"

    fwi_body = html.Div(
        [
            html.H2(
                f"{fwi_value} – {categorize_fwi(fwi_value).split()[0]}",
                className="mt-1 mb-1",
            ),
            html.P(weather_details, style={"fontSize": "14px", "margin": "0"}),
            html.P(
                f"Last update: {last_update}",
                style={"fontSize": "14px", "margin": "0", "color": "#555"},
            ),
        ],
        className="text-center",
    )

    fri_body = html.Div(
        [
            html.H2(
                f"{fri_value} – {fri_severity.split()[0]}",
                className="mt-1 mb-1",
            ),
            html.P(
                f"FRI = FSI * (1 + (FWI/100)) = {fsi_value} * (1 + ({fwi_value}/100))",
                style={"fontSize": "14px", "margin": "0"},
            ),
            html.P(
                f"FRI Severity: {fri_severity}",
                style={"fontSize": "14px", "margin": "0", "color": "#555"},
            ),
        ],
        className="text-center",
    )

    top_row = dbc.Row(
        [
            dbc.Col(section_card("Block Details", site_card_body), width=3),
            dbc.Col(
                section_card(
                    "Block Susceptibility Index",
                    fsi_body,
                    body_bg="#E0B654",
                    icon="fas fa-map-marker-alt",
                ),
                width=3,
            ),
            dbc.Col(
                section_card(
                    "Block Fire Weather Index",
                    fwi_body,
                    body_bg="#C8FFD4",
                    icon="fas fa-thermometer-half",
                ),
                width=3,
            ),
            dbc.Col(
                section_card(
                    "Block Fire Risk Index",
                    fri_body,
                    body_bg="#B3B3B3",
                    icon="fas fa-exclamation-triangle",
                ),
                width=3,
            ),
        ],
        className="g-3 mb-3",
    )

    current_summary = dbc.Row(
        [
            dbc.Col(
                section_card(
                    "Current Block Risk Summary",
                    html.Div(
                        [
                            html.P(
                                (
                                    f"Current wind direction is {wind_dir_label}"
                                    f"{f' ({wind_dir_deg}°)' if wind_dir_deg is not None else ''}. "
                                    f"Wind speed is {wind_text}, temperature is {temp_text}, "
                                    f"relative humidity is {rh_text}, and precipitation today is {precip_text}. "
                                    f"{'Live weather feed unavailable; fallback values are being shown. ' if source_status != 'live' else ''}"
                                    "These weather conditions influence how easily a fire may ignite and spread if one occurs."
                                ),
                                style={"fontSize": "14px", "marginBottom": "10px"},
                            ),
                            html.P(
                                (
                                    f"Fire Weather Index (FWI) is {fwi_value}, classified as "
                                    f"{categorize_fwi(fwi_value)}. "
                                    "FWI reflects the effect of current weather conditions such as temperature, "
                                    "humidity, wind, and precipitation on potential fire behaviour."
                                ),
                                style={"fontSize": "14px", "marginBottom": "10px"},
                            ),
                            html.P(
                                (
                                    f"Fire Susceptibility Index (FSI) is {fsi_value}, classified as {fsi_class}. "
                                    "FSI reflects the block’s underlying vulnerability based on environmental conditions, "
                                    "fuel load, community behaviour, and response capacity."
                                ),
                                style={"fontSize": "14px", "marginBottom": "10px"},
                            ),
                            html.P(
                                (
                                    f"Fire Risk Index (FRI) is {fri_value}, classified as {fri_severity}. "
                                    "FRI combines the current fire weather conditions with the block’s existing susceptibility "
                                    "to indicate the present level of operational fire risk."
                                ),
                                style={"fontSize": "14px", "marginBottom": "10px"},
                            ),
                            html.P(
                                (
                                    "Interpretation: FWI shows how favourable current weather is for fire ignition and spread, "
                                    "FSI shows how vulnerable the block is to fire, and FRI combines both to show the overall "
                                    "current fire risk. Higher FRI values mean greater need for preparedness, rapid response, "
                                    "equipment readiness, and prevention measures in this block."
                                ),
                                style={"fontSize": "14px", "marginBottom": "0"},
                            ),
                        ]
                    ),
                ),
                width=12,
            )
        ],
        className="g-3 mb-3",
    )

    advisory_section = dbc.Row(
        [
            dbc.Col(
                section_card(
                    "Fire Risk Reduction Advisory",
                    html.Div(
                        [
                            html.P(
                                "Open the action plan for recommended fire risk reduction measures based on the current susceptibility profile of this block.",
                                style={"fontSize": "14px", "marginBottom": "10px"},
                            ),
                            dbc.Button(
                                "Open Action Plan",
                                id="open-action-plan",
                                n_clicks=0,
                                color="primary",
                                className="me-2",
                            ),
                            dbc.Button(
                                "Access and Infrastructure",
                                id="btn-open-equipment-map",
                                n_clicks=0,
                                color="danger",
                                outline=True,
                            ),
                        ]
                    ),
                ),
                width=12,
            )
        ],
        className="g-3 mb-3",
    )

    # 6) FRI / FWI tabs row
    tabs_row = dbc.Row(
        [
            dbc.Col(
                section_card(
                    "Block Fire Risk Index",
                    html.Div(
                        [
                            dcc.Tabs(
                                id="block-fri-tabs",
                                value="current",
                                children=[
                                    dcc.Tab(label="Current", value="current"),
                                    dcc.Tab(label=OUTLOOK_LABEL, value="monthly"),
                                    dcc.Tab(label="Forecast", value="forecasted"),
                                ],
                            ),
                            html.Div(id="block-fri-content", className="mt-3"),
                        ]
                    ),
                ),
                width=6,
            ),
            dbc.Col(
                section_card(
                    "Block Fire Weather Index",
                    html.Div(
                        [
                            dcc.Tabs(
                                id="block-fwi-tabs",
                                value="current",
                                children=[
                                    dcc.Tab(label="Current", value="current"),
                                    dcc.Tab(label=OUTLOOK_LABEL, value="monthly"),
                                    dcc.Tab(label="Forecast", value="forecasted"),
                                ],
                            ),
                            html.Div(id="block-fwi-content", className="mt-3"),
                        ]
                    ),
                ),
                width=6,
            ),
        ],
        className="g-3 mb-3",
    )

    # 7) Block map (FRI)
    map_children = html.P("Block boundary data not available.")
    if block_geojson is not None:
        target = (block_name or "").strip().upper()

        camp_feats = []
        selected_feats = []

        for f in block_geojson["features"]:
            props = f.get("properties", {})
            camp_match = (props.get("CampName_1", "").strip().upper() == camp_name.strip().upper())
            if not camp_match:
                continue

            camp_feats.append(f)

            label = props.get("BlockLabel", "")
            name_ = props.get("BlockName", "")
            label_match = label.strip().upper() == target
            name_match = name_.strip().upper() == target
            if label_match or name_match:
                selected_feats.append(f)

        if camp_feats and selected_feats:
            selected_geojson = {
                "type": "FeatureCollection",
                "features": camp_feats,
            }

            coords = selected_feats[0]["geometry"]["coordinates"][0]
            lons, lats = zip(*coords)
            centre = {
                "lat": (max(lats) + min(lats)) / 2,
                "lon": (max(lons) + min(lons)) / 2,
            }

            df_sel = block_stats[["Block", "FRI"]].copy()
            df_sel = df_sel.rename(columns={"Block": "BlockLabel"})

            df_sel["is_selected"] = (
                df_sel["BlockLabel"].str.strip().str.upper() == target
            )

            df_sel["FRI_for_map"] = np.where(
                df_sel["is_selected"], df_sel["FRI"], 0
            )

            map_fig = px.choropleth_mapbox(
                df_sel,
                geojson=selected_geojson,
                locations="BlockLabel",
                featureidkey="properties.BlockLabel",
                color="FRI_for_map",
                range_color=(0, 100),
                color_continuous_scale=[
                    "#dddddd",
                    "#fee8c8",
                    "#fdbb84",
                    "#e34a33",
                ],
                center=centre,
                zoom=13,
                opacity=0.85,
                mapbox_style="carto-positron",
                hover_name="BlockLabel",
                hover_data={"FRI_for_map": False, "FRI": True},
            )

            map_fig.update_traces(
                marker_line_color="black",
                marker_line_width=1.5,
            )

            hover_text = (
                "<b>Block: %{hovertext}</b><br>"
                "FRI: %{customdata[0]}<br>"
                f"Rank: {rank} of {total_blocks} blocks in {camp_name}<br>"
                f"Approx. percentile: top {percentile}%<br>"
                f"Camp blocks by risk: "
                f"{b_extreme} Extreme, {b_high} High, {b_mod} Moderate, {b_low} Low"
                "<extra></extra>"
            )

            map_fig.update_traces(
                customdata=np.stack([df_sel["FRI"]], axis=-1),
                hovertemplate=hover_text,
            )

            map_fig.update_layout(
                margin={"l": 0, "r": 0, "t": 30, "b": 0},
                coloraxis_colorbar=dict(title="FRI", ticks="outside"),
            )

            map_children = dcc.Graph(
                figure=map_fig,
                config={"displayModeBar": False},
            )

    windy_src = (
        f"https://embed.windy.com/embed2.html?"
        f"lat={lat}&lon={lon}"
        f"&detailLat={lat}&detailLon={lon}"
        f"&zoom=14"
        f"&level=surface"
        f"&overlay=wind"
        f"&marker=true"
        f"&markerWidth=60"
        f"&markerHeight=60"
        f"&location=coordinates"
        f"&type=map"
    )
    windy_iframe = html.Iframe(
        id="windy-block-iframe",
        src=windy_src,
        style={"width": "100%", "height": "400px", "border": "none"},
    )

    maps_row = dbc.Row(
        [
            dbc.Col(
                section_card(
                    "Selected Block Boundary (FRI)",
                    map_children,
                ),
                width=6,
            ),
            dbc.Col(
                section_card(
                    "Live Wind Map (Block Focus)",
                    windy_iframe,
                ),
                width=6,
            ),
        ],
        className="g-3 mb-3",
    )

    # 8) FSI dimensions pill chart
    dims = ["Environment", "Fuel", "Behaviour", "Response"]
    scores = [math.ceil(dims_mean[d]) for d in dims]

    fig_dims = go.Figure()
    fig_dims.add_trace(
        go.Bar(
            x=[100] * 4,
            y=dims,
            orientation="h",
            marker=dict(color="lightgray"),
            width=0.4,
            showlegend=False,
            hoverinfo="none",
        )
    )
    fig_dims.add_trace(
        go.Scatter(
            x=scores,
            y=dims,
            mode="markers+text",
            marker=dict(
                size=[s / 100 * 40 + 20 for s in scores],
                color=["firebrick", "darkorange", "seagreen", "royalblue"],
                line=dict(color="black", width=1),
            ),
            text=[str(s) for s in scores],
            textposition="middle center",
            showlegend=False,
        )
    )
    fig_dims.update_xaxes(
        range=[0, 100],
        tickvals=[0, 20, 40, 60, 80, 100],
        title_text="Score",
    )
    fig_dims.update_yaxes(autorange="reversed")
    fig_dims.update_layout(
        title="FSI Dimensions (Block Summary)",
        margin=dict(l=60, r=40, t=50, b=40),
        height=300,
    )
    dims_graph = dcc.Graph(figure=fig_dims, config={"displayModeBar": False})


    # 9) Indicator score table
    indicator_df = build_indicator_score_table(block_data, cleaned_data)

    if not indicator_df.empty:
        indicator_table = dash_table.DataTable(
            columns=[
                {"name": "Indicator", "id": "Indicator"},
                {"name": "Score", "id": "Score"},
                {"name": "Rank", "id": "Rank"},
                {"name": "Mean", "id": "Mean"},
            ],
            data=indicator_df.to_dict("records"),
            style_table={
                "overflowX": "auto",
                "maxHeight": "500px",
                "overflowY": "auto",
            },
            style_cell={
                "textAlign": "center",
                "padding": "6px",
                "fontSize": "13px",
            },
            style_header={
                "fontWeight": "bold",
                "backgroundColor": "#f2f2f2",
            },
            style_data_conditional=[
                {
                    "if": {
                        "filter_query": "{Score} >= 75",
                        "column_id": "Score",
                    },
                    "backgroundColor": "#c93c3c",
                    "color": "white",
                },
                {
                    "if": {
                        "filter_query": "{Score} >= 50 && {Score} < 75",
                        "column_id": "Score",
                    },
                    "backgroundColor": "#e79c42",
                    "color": "black",
                },
                {
                    "if": {
                        "filter_query": "{Score} > 0 && {Score} < 50",
                        "column_id": "Score",
                    },
                    "backgroundColor": "#7bb7b3",
                    "color": "black",
                },
                {
                    "if": {
                        "filter_query": "{Mean} >= 75",
                        "column_id": "Mean",
                    },
                    "backgroundColor": "#c93c3c",
                    "color": "white",
                },
                {
                    "if": {
                        "filter_query": "{Mean} >= 50 && {Mean} < 75",
                        "column_id": "Mean",
                    },
                    "backgroundColor": "#e7b64a",
                    "color": "black",
                },
                {
                    "if": {
                        "filter_query": "{Mean} > 0 && {Mean} < 50",
                        "column_id": "Mean",
                    },
                    "backgroundColor": "#a8c29a",
                    "color": "black",
                },
            ],
        )
    else:
        indicator_table = html.P("No indicator score data available for this block.")

    bottom_row = dbc.Row(
        [
            dbc.Col(
                section_card(
                    "Block-Level Susceptibility Dimensions",
                    dims_graph,
                ),
                width=6,
            ),
            dbc.Col(
                section_card(
                    "Fire Susceptibility Indicator Scores",
                    html.Div(
                        [
                            html.P(
                                [
                                    html.Span("View "),
                                    html.Button(
                                        "Indicator Definitions",
                                        id="indicator-definition-link",
                                        n_clicks=0,
                                        style={
                                            "background": "none",
                                            "border": "none",
                                            "padding": "0",
                                            "margin": "0",
                                            "color": "#0d6efd",
                                            "textDecoration": "underline",
                                            "cursor": "pointer",
                                            "fontWeight": "bold",
                                        },
                                    ),
                                ],
                                style={"marginBottom": "10px"},
                            ),
                            indicator_table,
                        ]
                    ),
                ),
                width=6,
            ),
        ],
        className="g-3 mb-3",
    )

    return html.Div(
        [
            top_row,
            html.Hr(style={"borderTop": "1px solid #ccc"}),
            current_summary,
            html.Hr(style={"borderTop": "1px solid #ccc"}),
            advisory_section,
            html.Hr(style={"borderTop": "1px solid #ccc"}),
            tabs_row,
            html.Hr(style={"borderTop": "1px solid #ccc"}),
            maps_row,
            html.Hr(style={"borderTop": "1px solid #ccc"}),
            bottom_row,
        ]
    )

# -------------------------------------------------------------------
# BLOCK PAGE BODY CALLBACK
# -------------------------------------------------------------------

@app.callback(
    Output("action-plan-offcanvas", "is_open"),
    Input("open-action-plan", "n_clicks"),
    State("action-plan-offcanvas", "is_open"),
    prevent_initial_call=True,
)
def toggle_action_plan(n_clicks, is_open):
    if not n_clicks:
        return is_open
    return True

@app.callback(
    Output("action-plan-content", "children"),
    [
        Input("block-camp-dropdown", "value"),
        Input("block-block-dropdown", "value"),
    ],
)
def populate_action_plan(selected_camp, selected_block):
    if not selected_camp or not selected_block:
        return html.P("Please select a camp and block.")

    block_data = cleaned_data[
        (cleaned_data["CampName"] == selected_camp)
        & (cleaned_data["Block"] == selected_block)
    ]

    if block_data.empty:
        return html.P("No data available for this block.")

    dims_mean = block_data[["Environment", "Fuel", "Behaviour", "Response"]].mean()

    env_score = math.ceil(dims_mean["Environment"])
    fuel_score = math.ceil(dims_mean["Fuel"])
    beh_score = math.ceil(dims_mean["Behaviour"])
    res_score = math.ceil(dims_mean["Response"])

    advisory_points, advisory_overall = build_block_advisory_narrative(
        env_score, fuel_score, beh_score, res_score
    )

    return html.Div(
        [
            html.P(
                [
                    html.Strong("Camp: "),
                    selected_camp,
                    html.Br(),
                    html.Strong("Block: "),
                    selected_block,
                ],
                style={"fontSize": "14px"},
            ),
            html.Hr(),
            html.P(
                "Recommended actions based on the current susceptibility profile of this block:",
                style={"fontWeight": "bold", "marginBottom": "10px"},
            ),
            html.Ul(
                [html.Li(point) for point in advisory_points],
                style={"fontSize": "14px", "marginBottom": "10px"},
            ),
            html.P(
                advisory_overall,
                style={"fontSize": "14px", "marginBottom": "0"},
            ),
        ]
    )

@app.callback(
    Output("block-page-body", "children"),
    [Input("block-camp-dropdown", "value"), Input("block-block-dropdown", "value")],
)
def render_block_page_body(selected_camp, selected_block):
    from dash import html

    if not selected_camp:
        return html.P("Please select a camp.", style={"fontStyle": "italic"})
    if not selected_block:
        return html.P("Please select a block.", style={"fontStyle": "italic"})

    return build_block_level_content(selected_camp, selected_block)


# -------------------------------------------------------------------
# BLOCK FRI TABS
# -------------------------------------------------------------------
@app.callback(
    Output("block-fri-content", "children"),
    [
        Input("block-fri-tabs", "value"),
        Input("block-camp-dropdown", "value"),
        Input("block-block-dropdown", "value"),
    ],
)
def render_block_fri_tab(active_tab, camp_name, block_name):
    from dash import html

    if not camp_name or not block_name:
        return html.P("Please select a camp and block.", style={"fontStyle": "italic"})

    block_data = cleaned_data[
        (cleaned_data["CampName"] == camp_name)
        & (cleaned_data["Block"] == block_name)
    ]
    if block_data.empty:
        return html.P("No data available for this block.", style={"color": "red"})

    camp_all = cleaned_data[cleaned_data["CampName"] == camp_name]

    dims_mean = block_data[["Environment", "Fuel", "Behaviour", "Response"]].mean()
    fsi_value = math.ceil(
        (dims_mean["Environment"] + dims_mean["Fuel"] +
         dims_mean["Behaviour"] + dims_mean["Response"]) / 4
    )

    lat = block_data["Latitude"].mean()
    lon = block_data["Longitude"].mean()
    today_iso = date.today().isoformat()

    if active_tab == "current":
        fwi_today = math.ceil(get_fwi_xclim(lat, lon, date_for=today_iso))

        block_stats = (
            camp_all
            .groupby("Block")[["Environment", "Fuel", "Behaviour", "Response"]]
            .mean()
            .reset_index()
        )
        block_stats["FSI"] = (
            block_stats["Environment"] +
            block_stats["Fuel"] +
            block_stats["Behaviour"] +
            block_stats["Response"]
        ) / 4.0

        block_stats["FRI"] = np.ceil(block_stats["FSI"] * (1 + fwi_today / 100)).astype(int)
        block_stats["FRI_Class"] = block_stats["FRI"].apply(categorize_fri)

        df = block_stats.sort_values("FRI", ascending=False).reset_index(drop=True)

        risk_to_color_fri = {
            "Low risk": "green",
            "Moderate risk": "orange",
            "High risk": "red",
            "Extreme risk": "darkred",
        }
        colors = ["#EF553B" if b == block_name else "#636EFA" for b in df["Block"]]
        text_colors = [risk_to_color_fri[c] for c in df["FRI_Class"]]

        fig = px.bar(
            df,
            x="Block",
            y="FRI",
            text="FRI_Class",
            labels={"Block": "Block", "FRI": "Fire Risk Index"},
            title=f"Current FRI by Block in {camp_name}",
        )
        fig.update_traces(
            marker_color=colors,
            textposition="outside",
            textfont=dict(color=text_colors, size=11),
            showlegend=False,
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            plot_bgcolor="white",
            margin=dict(l=40, r=20, t=60, b=120),
            yaxis=dict(range=[0, 100]),
        )
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    elif active_tab == "monthly":

        outlook_df = build_monthly_outlook_df(
            lat,
            lon,
            base_fsi=fsi_value,
            year=OUTLOOK_YEAR,
        )

        if outlook_df.empty:
            return html.P(
                "Seasonal outlook data is unavailable.",
                style={"color": "red"},
            )

        fri_bar = px.bar(
            outlook_df,
            x="Month",
            y="FRI",
            color="FRI_Risk",
            text="FRI_Risk",
            title=f"Seasonal Fire Risk Outlook – Block {block_name} ({OUTLOOK_YEAR})",
            labels={"FRI": "Projected Fire Risk Index"},
            color_discrete_map={
                "Low risk": "green",
                "Moderate risk": "orange",
                "High risk": "red",
                "Extreme risk": "purple",
            },
            template="plotly_white",
        )

        fri_bar.update_traces(textposition="outside")
        fri_bar.update_yaxes(range=[0, 100])

        fri_heatmap = build_monthly_outlook_heatmap(
            outlook_df,
            value_col="FRI",
            risk_col="FRI_Risk",
            title=f"Monthly Fire Risk Outlook – Block {block_name} ({OUTLOOK_YEAR})",
        )

        narrative = build_monthly_outlook_narrative(
            block_name,
            outlook_df,
            year=OUTLOOK_YEAR,
        )

        return html.Div(
            [
                dcc.Graph(figure=fri_bar, config={"displayModeBar": False}),
                dcc.Graph(figure=fri_heatmap, config={"displayModeBar": False}),
                narrative,
            ]
        )

    elif active_tab == "seasonal_2026":
        outlook_df = build_monthly_outlook_df(lat, lon, base_fsi=fsi_value, year=2026)

        if outlook_df.empty:
            return html.P("Seasonal outlook data is unavailable.", style={"color": "red"})

        fri_heatmap = build_monthly_outlook_heatmap(
            outlook_df,
            value_col="FRI",
            risk_col="FRI_Risk",
            title=f"Projected Monthly FRI Outlook – Block {block_name} (2026)",
        )

        fri_bar = px.bar(
            outlook_df,
            x="Month",
            y="FRI",
            color="FRI_Risk",
            text="FRI_Risk",
            title=f"Projected Monthly Fire Risk Index – Block {block_name} (2026)",
            labels={"FRI": "Projected Fire Risk Index"},
            color_discrete_map={
                "Low risk": "green",
                "Moderate risk": "orange",
                "High risk": "red",
                "Extreme risk": "purple",
            },
            template="plotly_white",
        )
        fri_bar.update_traces(textposition="outside", showlegend=True)
        fri_bar.update_yaxes(range=[0, 100])

        narrative = build_monthly_outlook_narrative(block_name, outlook_df, year=2026)

        return html.Div(
            [
                dcc.Graph(figure=fri_bar, config={"displayModeBar": False}),
                dcc.Graph(figure=fri_heatmap, config={"displayModeBar": False}),
                narrative,
            ]
        )

    else:  # forecasted
        forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=float(fsi_value))

        if forecast_df.empty:
            return html.P("Forecast data is currently unavailable.", style={"color": "red"})

        fig = px.line(
            forecast_df,
            x="Date",
            y="FRI",
            color="FRI_Risk",
            markers=True,
            title=f"14-Day Projected FRI – Block {block_name}",
            labels={"FRI": "Projected Fire Risk Index", "FRI_Risk": "Severity"},
            color_discrete_map={
                "Low risk": "green",
                "Moderate risk": "orange",
                "High risk": "red",
                "Extreme risk": "purple",
            },
            hover_data={
                "Adjusted_FSI": True,
                "FWI": True,
                "wind": True,
                "rh": True,
                "precip": True,
                "wind_dir_label": True,
            },
        )
        fig.update_traces(mode="lines+markers")
        fig.update_yaxes(range=[0, 100], title="Projected Fire Risk Index")

        calendar_fig = build_fire_risk_outlook_calendar(
            forecast_df,
            value_col="FRI",
            risk_col="FRI_Risk",
            title=f"14-Day Fire Risk Outlook Calendar – Block {block_name}",
        )

        note = html.P(
            "Forecast uses stateful day-to-day FWI carryover and a short-term weather-adjusted susceptibility modifier.",
            style={"fontSize": "13px", "color": "#666", "marginTop": "8px"},
        )

        return html.Div(
            [
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                dcc.Graph(figure=calendar_fig, config={"displayModeBar": False}),
                note,
            ]
        )


# -------------------------------------------------------------------
# BLOCK FWI TABS
# -------------------------------------------------------------------
@app.callback(
    Output("block-fwi-content", "children"),
    [
        Input("block-fwi-tabs", "value"),
        Input("block-camp-dropdown", "value"),
        Input("block-block-dropdown", "value"),
    ],
)
def render_block_fwi_tab(active_tab, camp_name, block_name):
    from dash import html

    if not camp_name or not block_name:
        return html.P("Please select a camp and block.", style={"fontStyle": "italic"})

    block_data = cleaned_data[
        (cleaned_data["CampName"] == camp_name)
        & (cleaned_data["Block"] == block_name)
    ]
    if block_data.empty:
        return html.P("No data available for this block.", style={"color": "red"})

    camp_all = cleaned_data[cleaned_data["CampName"] == camp_name]
    lat = block_data["Latitude"].mean()
    lon = block_data["Longitude"].mean()
    today_iso = date.today().isoformat()

    if active_tab == "current":
        centroids = (
            camp_all.groupby("Block")[["Latitude", "Longitude"]]
            .mean()
            .reset_index()
        )
        records = []
        for _, r in centroids.iterrows():
            fwi_b = math.ceil(
                get_fwi_xclim(r["Latitude"], r["Longitude"], date_for=today_iso)
            )
            records.append(
                {
                    "Block": r["Block"],
                    "FWI": fwi_b,
                    "Risk": categorize_fwi(fwi_b),
                }
            )
        df = pd.DataFrame(records).sort_values("FWI", ascending=False).reset_index(drop=True)

        risk_to_color = {
            "Low fire danger": "green",
            "Moderate fire danger": "goldenrod",
            "High fire danger": "orange",
            "Severe fire danger": "red",
        }
        colors = ["#EF553B" if b == block_name else "#636EFA" for b in df["Block"]]
        text_colors = df["Risk"].map(risk_to_color)

        fig = px.bar(
            df,
            x="Block",
            y="FWI",
            text="Risk",
            labels={"Block": "Block", "FWI": "Fire Weather Index"},
            title=f"Current FWI by Block in {camp_name}",
        )
        fig.update_traces(
            marker_color=colors,
            textposition="outside",
            textfont=dict(color=text_colors, size=11),
            showlegend=False,
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            plot_bgcolor="white",
            margin=dict(l=40, r=20, t=60, b=120),
            yaxis=dict(range=[0, 100]),
        )

        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    elif active_tab == "monthly":

        outlook_df = build_monthly_outlook_df(
            lat,
            lon,
            base_fsi=50,
            year=OUTLOOK_YEAR,
        )

        if outlook_df.empty:
            return html.P(
                "Seasonal outlook data is unavailable.",
                style={"color": "red"},
            )

        fwi_bar = px.bar(
            outlook_df,
            x="Month",
            y="FWI",
            color="FWI_Risk",
            text="FWI_Risk",
            title=f"Projected Monthly Fire Weather Index – Block {block_name} (2026)",
            labels={"FWI": "Fire Weather Index"},
            color_discrete_map={
                "Low fire danger": "green",
                "Moderate fire danger": "goldenrod",
                "High fire danger": "orange",
                "Severe fire danger": "red",
            },
            template="plotly_white",
        )

        fwi_bar.update_traces(textposition="outside")
        fwi_bar.update_yaxes(range=[0, 100])

        fwi_heatmap = build_monthly_outlook_heatmap(
            outlook_df,
            value_col="FWI",
            risk_col="FWI_Risk",
            title=f"Monthly Fire Weather Outlook – Block {block_name} ({OUTLOOK_YEAR})",
        )

        return html.Div(
            [
                dcc.Graph(figure=fwi_bar, config={"displayModeBar": False}),
                dcc.Graph(figure=fwi_heatmap, config={"displayModeBar": False}),
                html.P(
                    "This seasonal outlook shows the projected fire-weather pattern across the year based on climatological fire-weather behaviour.",
                    style={"fontSize": "14px", "marginTop": "10px"},
                ),
            ]
        )

    elif active_tab == "seasonal_2026":
        outlook_df = build_monthly_outlook_df(lat, lon, base_fsi=50, year=2026)

        if outlook_df.empty:
            return html.P("Seasonal outlook data is unavailable.", style={"color": "red"})

        fwi_heatmap = build_monthly_outlook_heatmap(
            outlook_df,
            value_col="FWI",
            risk_col="FWI_Risk",
            title=f"Projected Monthly FWI Outlook – Block {block_name} (2026)",
        )

        fwi_bar = px.bar(
            outlook_df,
            x="Month",
            y="FWI",
            color="FWI_Risk",
            text="FWI_Risk",
            title=f"Seasonal Fire Weather Outlook – Block {block_name} ({OUTLOOK_YEAR})",
            labels={"FWI": "Projected Fire Weather Index"},
            color_discrete_map={
                "Low fire danger": "green",
                "Moderate fire danger": "goldenrod",
                "High fire danger": "orange",
                "Severe fire danger": "red",
            },
            template="plotly_white",
        )
        fwi_bar.update_traces(textposition="outside", showlegend=True)
        fwi_bar.update_yaxes(range=[0, 100])

        return html.Div(
            [
                dcc.Graph(figure=fwi_bar, config={"displayModeBar": False}),
                dcc.Graph(figure=fwi_heatmap, config={"displayModeBar": False}),
                html.P(
                    "This seasonal outlook uses monthly fire-weather patterns to indicate which months in 2026 are likely to present higher fire-weather danger.",
                    style={"fontSize": "14px", "marginTop": "10px"},
                ),
            ]
        )

    else:  # forecasted
        forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=float(50))

        if forecast_df.empty:
            return html.P("Forecast data is currently unavailable.", style={"color": "red"})

        fig = px.line(
            forecast_df,
            x="Date",
            y="FWI",
            color="FWI_Risk",
            markers=True,
            title=f"14-Day Stateful FWI Forecast – Block {block_name}",
            labels={"FWI": "Fire Weather Index", "FWI_Risk": "Danger Level"},
            color_discrete_map={
                "Low fire danger": "green",
                "Moderate fire danger": "goldenrod",
                "High fire danger": "orange",
                "Severe fire danger": "red",
            },
            hover_data={
                "wind": True,
                "rh": True,
                "precip": True,
                "wind_dir_label": True,
                "FFMC": True,
                "DMC": True,
                "DC": True,
            },
        )
        fig.update_traces(mode="lines+markers")
        fig.update_yaxes(range=[0, 100], title="Fire Weather Index")

        calendar_fig = build_fire_risk_outlook_calendar(
            forecast_df,
            value_col="FWI",
            risk_col="FWI_Risk",
            title=f"14-Day Fire Weather Outlook Calendar – Block {block_name}",
        )

        note = html.P(
            "Forecast uses stateful day-to-day FWI carryover across the 14-day period.",
            style={"fontSize": "13px", "color": "#666", "marginTop": "8px"},
        )

        return html.Div(
            [
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                dcc.Graph(figure=calendar_fig, config={"displayModeBar": False}),
                note,
            ]
        )

# -------------------------------------------------------------------
# CONTACT COLLAPSE
# -------------------------------------------------------------------
@app.callback(
    [Output("contact-collapse", "is_open"), Output("contact-content", "children")],
    [Input("contact-toggle", "n_clicks"), Input("camp-dropdown", "value")],
    [State("contact-collapse", "is_open")],
)
def toggle_and_populate_contact(n_clicks, selected_camp, is_open):
    if not n_clicks:
        return False, dash.no_update

    from dash import html

    row = response_details.loc[response_details.CampName == selected_camp]
    if row.empty:
        return not is_open, html.P("No contact info available for this camp.")

    row = row.iloc[0]
    content = html.Div(
        [
            html.P(
                [
                    html.Strong("Site-Management focal: "),
                    row["SM focal(Name and Mobile No)"],
                ]
            ),
            html.P(
                [
                    html.Strong("Sector Focals: "),
                    row["Sector Focals(Name and Mobile No)"],
                ]
            ),
            html.P(
                [
                    html.Strong("DMU Lead: "),
                    row["DMU Lead(Name and Mobile No)"],
                ]
            ),
            html.P(
                [
                    html.Strong("Infrastructure: "),
                    row["List of infrastructure"],
                ]
            ),
        ],
        style={"fontSize": "14px"},
    )
    return not is_open, content


# -------------------------------------------------------------------
# SITE-LEVEL FWI TABS
# -------------------------------------------------------------------
@app.callback(
    [Output("site-fwi-content", "children"), Output("site-fwi-narrative", "children")],
    [Input("camp-dropdown", "value"), Input("site-fwi-tabs", "value")],
)
def render_fwi_tab(selected_camp, active_tab):
    row = camp_summary[camp_summary["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update, dash.no_update

    row = row.iloc[0]
    lat, lon = row["Latitude"], row["Longitude"]

    if active_tab == "monthly":
        year = date.today().year - 1
        monthly = get_monthly_fwi_xclim(lat, lon, year)
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        df = pd.DataFrame({"month": months, "value": monthly})
        df["value"] = (
            pd.to_numeric(df["value"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
            .round(0)
            .astype(int)
        )
        df["risk"] = df["value"].apply(categorize_fwi)

        risk_to_color = {
            "Low fire danger": "green",
            "Moderate fire danger": "goldenrod",
            "High fire danger": "orange",
            "Severe fire danger": "red",
        }
        df["text_color"] = df["risk"].map(risk_to_color)

        fig = px.bar(
            df,
            x="month",
            y="value",
            labels={"month": "Month", "value": "Fire Weather Index"},
            title=f"Monthly Fire Weather Index ({year}) for {selected_camp}",
        )
        fig.update_traces(
            marker_color="steelblue",
            text=df["risk"],
            textposition="outside",
            textfont=dict(color=df["text_color"], size=12),
            showlegend=False,
        )
        fig.update_yaxes(range=[0, 100])

        narrative = build_monthly_risk_narrative(
            selected_camp, df.copy(), value_col="value", index_name="Fire Weather Index"
        )

        return dcc.Graph(figure=fig, config={"displayModeBar": False}), narrative

    elif active_tab == "current":
        df = (
            camp_summary[["CampName", "FWI"]]
            .assign(FWI=lambda d: d.FWI.round(0).astype(int))
            .sort_values("FWI", ascending=False)
            .reset_index(drop=True)
        )

        fwi_sel = df.loc[df.CampName == selected_camp, "FWI"].iloc[0]
        rank = int(df.index[df.CampName == selected_camp][0]) + 1
        total = len(df)

        colors = ["#EF553B" if c == selected_camp else "#636EFA" for c in df.CampName]
        df["Risk"] = df["FWI"].apply(categorize_fwi)

        risk_to_color = {
            "Low fire danger": "green",
            "Moderate fire danger": "goldenrod",
            "High fire danger": "orange",
            "Severe fire danger": "red",
        }
        text_colors = df["Risk"].map(risk_to_color)

        fig = px.bar(
            df,
            x="CampName",
            y="FWI",
            text="Risk",
            labels={"CampName": "Camp", "FWI": "Fire Weather Index"},
            title=f"Current Fire Weather Index (Rank {rank}/{total})",
        )
        fig.update_traces(
            marker_color=colors,
            textposition="outside",
            textfont=dict(color=text_colors, size=12),
            showlegend=False,
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            plot_bgcolor="white",
            margin=dict(l=40, r=20, t=60, b=120),
        )
        fig.update_yaxes(range=[0, 100])

        narrative = build_current_weather_narrative(selected_camp, df.copy())
        return dcc.Graph(figure=fig, config={"displayModeBar": False}), narrative

    else:  # forecasted
        forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=50)

        if forecast_df.empty:
            return (
                html.P(
                    "Forecast data is currently unavailable.",
                    style={"color": "red"},
                ),
                dash.no_update,
            )

        fig = px.line(
            forecast_df,
            x="Date",
            y="FWI",
            color="FWI_Risk",
            markers=True,
            title=f"14-Day Stateful Fire Weather Index Forecast for {selected_camp}",
            labels={
                "FWI": "Fire Weather Index",
                "FWI_Risk": "Danger Level",
            },
        )
        fig.update_traces(mode="lines+markers")
        fig.update_yaxes(range=[0, 100], title="Fire Weather Index")

        calendar_fig = build_fire_risk_outlook_calendar(
            forecast_df,
            value_col="FWI",
            risk_col="FWI_Risk",
            title=f"14-Day Fire Weather Outlook Calendar – {selected_camp}",
        )

        forecast_df_narr = forecast_df.copy()
        forecast_df_narr["Risk"] = forecast_df_narr["FWI_Risk"]

        narrative = build_forecast_narrative(
            selected_camp,
            forecast_df_narr,
            value_col="FWI",
            index_name="Fire Weather Index",
        )

        content = html.Div(
            [
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                dcc.Graph(figure=calendar_fig, config={"displayModeBar": False}),
            ]
        )

        return content, narrative

# -------------------------------------------------------------------
# SITE-LEVEL FRI TABS
# -------------------------------------------------------------------
@app.callback(
    Output("site-fri-content", "children"),
    [Input("camp-dropdown", "value"), Input("site-fri-tabs", "value")],
)
def render_fri_tab(selected_camp, active_tab):
    row = camp_summary[camp_summary["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update
    row = row.iloc[0]

    lat, lon = row["Latitude"], row["Longitude"]
    fsi_val = float(row["FSI_Calculated"])

    if active_tab == "monthly":
        year = date.today().year - 1
        fsi = fsi_val

        monthly_fwi = get_monthly_fwi_xclim(lat, lon, year)
        monthly_fri = [fsi * (1 + w / 100) for w in monthly_fwi]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        df = pd.DataFrame({"month": months, "fri": monthly_fri})
        df["fri"] = (
            pd.to_numeric(df["fri"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
            .round(0)
            .astype(int)
        )
        df["risk"] = df["fri"].apply(categorize_fri)

        risk_to_color = {
            "Low risk": "green",
            "Moderate risk": "orange",
            "High risk": "red",
            "Extreme risk": "darkred",
        }
        df["text_color"] = df["risk"].map(risk_to_color)

        fig = px.bar(
            df,
            x="month",
            y="fri",
            labels={"month": "Month", "fri": "Fire Risk Index"},
            title=f"Monthly Fire Risk Index ({year}) for {selected_camp}",
            template="plotly_white",
        )
        fig.update_traces(
            marker_color="steelblue",
            text=df["risk"],
            textposition="outside",
            textfont=dict(color=df["text_color"], size=12),
            showlegend=False,
        )
        fig.update_yaxes(range=[0, 100])

        narrative = build_monthly_risk_narrative(
            selected_camp, df.copy(), value_col="fri", index_name="Fire Risk Index"
        )
        return html.Div(
            [
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                html.Br(),
                narrative,
            ]
        )

    elif active_tab == "current":
        df = (
            camp_summary[["CampName", "FRI", "FRI_Class"]]
            .sort_values("FRI", ascending=False)
            .reset_index(drop=True)
        )
        df["FRI"] = np.ceil(df["FRI"]).astype(int)

        fri_sel = df.loc[df.CampName == selected_camp, "FRI"].iloc[0]
        cls_sel = df.loc[df.CampName == selected_camp, "FRI_Class"].iloc[0]
        rank = int(df.index[df.CampName == selected_camp][0]) + 1
        total = len(df)

        colors = ["#EF553B" if c == selected_camp else "#636EFA" for c in df["CampName"]]

        risk_to_color = {
            "Extreme risk": "darkred",
            "High risk": "red",
            "Moderate risk": "orange",
            "Low risk": "green",
        }
        text_colors = [risk_to_color[c] for c in df["FRI_Class"]]

        fig = px.bar(
            df,
            x="CampName",
            y="FRI",
            text="FRI_Class",
            title=f"Current FRI Comparison (Rank {rank}/{total})",
            labels={"CampName": "Camp", "FRI": "Fire Risk Index"},
            template="plotly_white",
        )
        fig.update_traces(
            marker_color=colors,
            textposition="outside",
            textfont=dict(color=text_colors, size=12),
            showlegend=False,
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            plot_bgcolor="white",
            margin=dict(l=40, r=20, t=60, b=120),
        )
        fig.update_yaxes(range=[0, 100])

        narrative = build_current_risk_narrative(selected_camp, df.copy())
        return html.Div(
            [
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                html.Br(),
                narrative,
            ]
        )

    else:  # forecasted
        forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=fsi_val)

        if forecast_df.empty:
            return html.Div(
                [html.P("Forecast data is currently unavailable.", style={"color": "red"})]
            )

        fig = px.line(
            forecast_df,
            x="Date",
            y="FRI",
            color="FRI_Risk",
            markers=True,
            title=f"14-Day Projected FRI Forecast for {selected_camp}",
            labels={"FRI": "Projected Fire Risk Index", "FRI_Risk": "Severity"},
            color_discrete_map={
                "Low risk": "green",
                "Moderate risk": "orange",
                "High risk": "red",
                "Extreme risk": "purple",
            },
        )
        fig.update_traces(mode="lines+markers")
        fig.update_yaxes(range=[0, 100], title="Projected Fire Risk Index")

        calendar_fig = build_fire_risk_outlook_calendar(
            forecast_df,
            value_col="FRI",
            risk_col="FRI_Risk",
            title=f"14-Day Fire Risk Outlook Calendar – {selected_camp}",
        )

        forecast_df_narr = forecast_df.copy()
        forecast_df_narr["Risk"] = forecast_df_narr["FRI_Risk"]

        narrative = build_forecast_narrative(
        selected_camp,
        forecast_df_narr,
        value_col="FRI",
        index_name="Projected Fire Risk Index",
)
        return (
            html.Div(
                [
                    dcc.Graph(figure=fig, config={"displayModeBar": False}),
                    dcc.Graph(figure=calendar_fig, config={"displayModeBar": False}),
                ]
            ),
            narrative,
        )


# -------------------------------------------------------------------
# SITE-LEVEL MAIN DASHBOARD UPDATE
# -------------------------------------------------------------------
@app.callback(
    [
        Output("site-details", "children"),
        Output("fsi-index", "children"),
        Output("fwi-index", "children"),
        Output("fri-index", "children"),
        Output("block-bar-chart", "figure"),
        Output("fire-risk-map", "figure"),
        Output("susceptibility-table", "data"),
    ],
    Input("camp-dropdown", "value"),
)
def update_dashboard(selected_camp):
    from dash import html

    camp_data = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if camp_data.empty:
        return (
            "No data available",
            "-",
            "-",
            "-",
            {},
            {},
            [],
        )

    camp_row = camp_summary.loc[camp_summary["CampName"] == selected_camp]
    if camp_row.empty:
        return (
            "No summary data",
            "-",
            "-",
            "-",
            {},
            {},
            [],
        )
    camp = camp_row.iloc[0]

    # Assessment date range
    assessment_text = "N/A"
    if "assessment_date" in camp_data.columns:
        today_series = pd.to_datetime(camp_data["assessment_date"], errors="coerce").dropna()
        if not today_series.empty:
            min_date = today_series.min().date().isoformat()
            max_date = today_series.max().date().isoformat()
            assessment_text = min_date if min_date == max_date else f"{min_date} to {max_date}"

    # Site population
    population_text = "N/A"
    pop_col = "ENV_003a"
    if pop_col in camp_data.columns:
        site_pop = pd.to_numeric(camp_data[pop_col], errors="coerce").fillna(0).sum()
        population_text = f"{site_pop:,.0f}"

    site_container = html.Div(
        [
            html.P([html.Strong("Site name: "), selected_camp]),
            html.P([html.Strong("Assessment date: "), assessment_text]),
            html.P([html.Strong("Site population: "), population_text]),
        ],
        style={"fontSize": "14px"},
    )

    # FSI card
    fsi_value = math.ceil(camp["FSI_Calculated"])
    fsi_class = classify_fsi(fsi_value)

    fsi_text = html.Div(
        [
            html.H2(f"{fsi_value} – {fsi_class}", style={"display": "inline-block"}),
            html.P(
                f"(Environment: {math.ceil(camp['Environment'])}, "
                f"Fuel: {math.ceil(camp['Fuel'])}, "
                f"Behaviour: {math.ceil(camp['Behaviour'])}, "
                f"Response: {math.ceil(camp['Response'])})",
                style={"fontSize": "14px", "color": "#555"},
            ),
        ]
    )

    lat, lon = camp["Latitude"], camp["Longitude"]
    w_today = get_weather_noon(lat, lon, date.today().isoformat())

    fwi_value = int(round(camp["FWI"]))
    fri_value = int(round(camp["FRI"]))
    fri_severity = categorize_fri(fri_value).split()[0]
    fri_label = f"{fri_value} – {fri_severity}"

    weather_details = (
        f"Temp: {w_today['temp']}°C; "
        f"RH: {w_today['rh']}%; "
        f"Wind: {w_today['wind']} km/h; "
        f"Precip: {w_today['precip']} mm"
    )
    last_update = f"{date.today().isoformat()} 13:00 LST"

    fwi_text = html.Div(
        [
            html.H2(
                f"{fwi_value} – {categorize_fwi(fwi_value).split()[0]}",
                className="mt-1 mb-0",
                style={"display": "inline-block"},
            ),
            html.P(weather_details, style={"fontSize": "14px", "margin": "0"}),
            html.P(
                f"Last update: {last_update}",
                style={"fontSize": "14px", "margin": "0", "color": "#555"},
            ),
        ]
    )

    short_fri_label = fri_severity
    fri_text = html.Div(
        [
            html.H2(
                f"{fri_value} – {short_fri_label}",
                className="mt-1 mb-0",
                style={"display": "inline-block"},
            ),
            html.P(
                f"FRI = FSI * (1 + (FWI/100)) = {fsi_value} * (1 + ({fwi_value}/100))",
                style={"fontSize": "14px", "margin": "0"},
            ),
            html.P(
                f"FRI Severity: {categorize_fri(fri_value)}",
                style={"fontSize": "14px", "margin": "0", "color": "#555"},
            ),
        ]
    )

    # Block-level bar chart
    block_means = (
        camp_data.groupby("Block")[["Environment", "Fuel", "Behaviour", "Response"]]
        .mean()
        .reset_index()
    )
    melted = block_means.melt(
        id_vars="Block", var_name="Dimension", value_name="Score"
    )
    melted["Score"] = melted["Score"].round(0).astype(int)
    block_bar_fig = px.bar(
        melted,
        x="Block",
        y="Score",
        color="Dimension",
        barmode="group",
        text="Score",
    )
    block_bar_fig.update_traces(texttemplate="%{text}", textposition="outside")

    # Camp boundary map for selected camp
    if geojson_data is not None:
        selected_features = [
            feat
            for feat in geojson_data["features"]
            if feat.get("properties", {}).get("CampName") == selected_camp
        ]
    else:
        selected_features = []

    if selected_features:
        selected_geojson = {
            "type": "FeatureCollection",
            "features": selected_features,
        }
        coords = selected_features[0]["geometry"]["coordinates"][0]
        lons, lats = zip(*coords)
        centre = {
            "lat": (max(lats) + min(lats)) / 2,
            "lon": (max(lons) + min(lons)) / 2,
        }

        df_sel = pd.DataFrame([{"CampName": selected_camp, "FRI": fri_value}])

        map_fig = px.choropleth_mapbox(
            df_sel,
            geojson=selected_geojson,
            locations="CampName",
            featureidkey="properties.CampName",
            color="FRI",
            range_color=(0, 100),
            color_continuous_scale="OrRd",
            center=centre,
            zoom=11,
            opacity=0.6,
            mapbox_style="carto-positron",
            hover_name="CampName",
            hover_data={"FRI": False},
        )
        map_fig.update_traces(
            hovertemplate="<b>%{hovertext}</b><br>" f"FRI: {fri_label}<extra></extra>"
        )
        map_fig.update_layout(
            margin={"l": 0, "r": 0, "t": 30, "b": 0},
            uirevision=selected_camp,
        )
    else:
        map_fig = {}

    # Block-level susceptibility table
    table_df = camp_data[["Block", "FSI_Calculated", "FSI_Class"]].copy()
    table_df["FSI_Calculated"] = table_df["FSI_Calculated"].round(0).astype(int)
    table_df = table_df.rename(
        columns={
            "Block": "Site Block",
            "FSI_Calculated": "FSI Score",
        }
    )
    table_data = table_df.to_dict("records")

    return (
        site_container,
        fsi_text,
        fwi_text,
        fri_text,
        block_bar_fig,
        map_fig,
        table_data,
    )


# -------------------------------------------------------------------
# WINDY IFRAME (SITE-LEVEL)
# -------------------------------------------------------------------
@app.callback(
    Output("windy-iframe", "src"),
    Input("camp-dropdown", "value"),
)
def update_windy_src(selected_camp):
    row = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update

    lat = row.iloc[0]["Latitude"]
    lon = row.iloc[0]["Longitude"]

    return (
        f"https://embed.windy.com/embed2.html?"
        f"lat={lat}&lon={lon}"
        f"&detailLat={lat}&detailLon={lon}"
        f"&zoom=10"
        f"&level=surface"
        f"&overlay=wind"
        f"&marker=true"
        f"&markerWidth=60"
        f"&markerHeight=60"
        f"&location=coordinates"
        f"&type=map"
    )


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)