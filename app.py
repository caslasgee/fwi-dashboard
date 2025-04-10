import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
import plotly.express as px
import pandas as pd
import numpy as np
import requests
import math
import json
from datetime import datetime
from dash.dependencies import Input, Output

# ------------------ Data Loading and Preparation ------------------ #
aor_data = pd.read_excel("AOR.xlsx")
fire_data = pd.read_csv("Fire Susceptability Data Block.csv")

# Load GeoJSON (Camp Boundaries)
try:
    with open("200908_RRC_Outline_Camp_AL1.json", "r") as f:
        geojson_data = json.load(f)
except FileNotFoundError:
    geojson_data = None

# Standardize column names & merge datasets
aor_data.rename(columns={'New_Camp_Name': 'CampName'}, inplace=True)
merged_data = pd.merge(fire_data, aor_data, on='CampName', how='left')
if "Block" not in merged_data.columns:
    raise ValueError("❌ 'Block' column not found in dataset! Please check the data.")
merged_data['FSI_Calculated'] = (
    merged_data['Environment'].fillna(0) +
    merged_data['Fuel'].fillna(0) +
    merged_data['Behaviour'].fillna(0) +
    merged_data['Response'].fillna(0)
) / 4
cleaned_data = merged_data.dropna(subset=['Latitude', 'Longitude']).copy()

def classify_fsi(fsi):
    if fsi >= 67:
        return "Urgent"
    elif fsi >= 33:
        return "High"
    else:
        return "Moderate"

cleaned_data["FSI_Class"] = cleaned_data["FSI_Calculated"].apply(classify_fsi)

# ------------------ Weather Data Fetching from wttr.in ------------------ #
def get_wttr_data(lat, lon):
    """
    Fetch the current weather data from wttr.in.
    Returns a dictionary with:
      - temp: Temperature in °C
      - humidity: Humidity in %
      - windspeed: Wind speed in km/h
      - precip: Precipitation in mm
      - local_time: localObsDateTime from wttr.in
    """
    url = f"https://wttr.in/{lat},{lon}?format=j1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        weather = response.json()
        current = weather['current_condition'][0]
        temp = float(current['temp_C'])
        humidity = float(current['humidity'])
        windspeed = float(current['windspeedKmph'])
        precip = float(current.get('precipMM', 0))
        local_time = current.get('localObsDateTime', "N/A")
        return {"temp": temp, "humidity": humidity, "windspeed": windspeed, "precip": precip, "local_time": local_time}
    except Exception as e:
        print(f"Error fetching weather data: {e}")
        return {"temp": "N/A", "humidity": "N/A", "windspeed": "N/A", "precip": "N/A", "local_time": "N/A"}

# ------------------ FWI Calculation using a Simple Formula ------------------ #
def calc_fwi_simple(temp, rh, wind, rain):
    """
    Computes FWI using:
      FWI = 0.5 * Temperature + 0.1 * Humidity + 0.3 * Wind Speed - 0.2 * Rainfall
    """
    return 0.5 * temp + 0.1 * rh + 0.3 * wind - 0.2 * rain

def get_fwi_standard(lat, lon):
    """
    Fetches current weather from wttr.in and computes FWI.
    """
    raw = get_wttr_data(lat, lon)
    if raw["temp"] != "N/A":
        return round(calc_fwi_simple(raw["temp"], raw["humidity"], raw["windspeed"], raw["precip"]), 1)
    else:
        return 0

# ------------------ categorize_fwi Function ------------------ #
def categorize_fwi(fwi):
    if fwi <= 20:
        return "Low fire danger"
    elif fwi <= 30:
        return "Moderate fire danger"
    else:
        return "Severe fire danger"

# ------------------ short_categorize_fri ------------------ #
def short_categorize_fri(value):
    """
    Returns the first word of the severity description.
    For example, "High" from "High fire danger".
    """
    return categorize_fwi(value).split()[0]

# ------------------ categorize_fri Function for FRI Severity ------------------ #
def categorize_fri(fri):
    if fri < 50:
        return "Low risk"
    elif fri < 75:
        return "Moderate risk"
    elif fri < 100:
        return "High risk"
    else:
        return "Extreme risk"

# ------------------ Narrative Helper ------------------ #
def generate_narrative(labels, values):
    groups = {"Low": [], "Moderate to high": [], "Severe": []}
    for label, val in zip(labels, values):
        cat = categorize_fwi(val)
        if cat == "Low fire danger":
            key = "Low"
        elif cat == "Moderate fire danger":
            key = "Moderate to high"
        else:
            key = "Severe"
        groups[key].append((label, math.ceil(val)))
    narrative = []
    for severity, items in groups.items():
        if items:
            item_text = ", ".join([f"{lbl}: {v}" for lbl, v in items])
            narrative.append(f"{severity} FWI: {item_text}.")
    return " ".join(narrative)

# ------------------ NASA POWER Monthly FWI Function ------------------ #
def get_monthly_fwi_nasa(lat, lon, year):
    url = (
        "https://power.larc.nasa.gov/api/temporal/monthly/point"
        f"?start={year}&end={year}"
        f"&latitude={lat}&longitude={lon}"
        "&community=sb"
        "&parameters=T2M,T2M_MAX"
        "&format=json"
        "&user=caslas"
        "&header=true"
        "&time-standard=utc"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data_json = resp.json()
        params = data_json["properties"]["parameter"]
        monthly_fwi = []
        default_rh = 50
        default_wind = 10
        default_rain = 2
        for month in range(1, 13):
            m_str = str(month).zfill(2)
            t2m = params["T2M"][m_str]
            t2m_max = params["T2M_MAX"][m_str]
            avg_temp = (t2m + t2m_max) / 2.0
            monthly_val = max(round(calc_fwi_simple(avg_temp, default_rh, default_wind, default_rain), 2), 0)
            monthly_fwi.append(monthly_val)
        return monthly_fwi
    except Exception as e:
        print(f"Error fetching monthly FWI from NASA POWER: {e}")
        return list(np.random.randint(10, 35, size=12))

def generate_grouped_fwi_narrative(month_names, monthly_fwi):
    return [html.P(generate_narrative(month_names, monthly_fwi))]

def create_fsi_dimensions_figure(camp_data):
    env_mean = camp_data["Environment"].mean()
    fuel_mean = camp_data["Fuel"].mean()
    beh_mean = camp_data["Behaviour"].mean()
    resp_mean = camp_data["Response"].mean()
    dims = ["Environment", "Fuel", "Behaviour", "Response"]
    values = [env_mean, fuel_mean, beh_mean, resp_mean]
    df = pd.DataFrame({"Dimension": dims, "Score": values})
    fig = px.scatter(
        df,
        x="Score",
        y="Dimension",
        color="Dimension",
        size="Score",
        size_max=30,
        range_x=[0, 100],
        title="Dimensions (Bubble Chart)"
    )
    fig.update_yaxes(categoryorder="array", categoryarray=dims[::-1])
    fig.update_layout(
        xaxis=dict(tickvals=[0, 20, 40, 60, 80, 100]),
        showlegend=False,
        margin=dict(l=50, r=50, t=50, b=50)
    )
    return fig

# ------------------ External Stylesheets: Font Awesome ------------------ #
FA_URL = "https://use.fontawesome.com/releases/v5.15.4/css/all.css"

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, FA_URL]
)
app.title = "Fire Risk Analysis - Site-Level"
app.config.suppress_callback_exceptions = True

# ------------------ Navigation Bar ------------------ #
navbar = dbc.Navbar(
    dbc.Container(
        fluid=True,
        children=[
            dbc.Row([
                # LEFT: Fire icon image + Title pinned left
                dbc.Col(
                    dbc.NavbarBrand(
                        [
                            html.Img(
                                src="https://upload.wikimedia.org/wikipedia/commons/9/99/FireIcon.svg",
                                style={"height": "30px", "marginRight": "10px"}
                            ),
                            "Fire Risk Analysis"
                        ],
                        className="text-white",
                        style={"fontSize": "28px", "fontWeight": "bold", "marginLeft": "0"}
                    ),
                    width="auto",
                    style={"paddingLeft": "0"}
                ),
                # Middle: Nav Links (if needed)
                dbc.Col(
                    dbc.Nav([
                        dbc.NavItem(dbc.NavLink("Overview", href="/overview", active="exact")),
                        dbc.NavItem(dbc.NavLink("Site Level", href="/", active="exact")),
                        dbc.NavItem(dbc.NavLink("About", href="/about", active="exact"))
                    ], navbar=True),
                    width="auto"
                ),
                # RIGHT: Inline "Select a camp:" label + Dropdown
                dbc.Col(
                    html.Div([
                        html.Span("Select a camp:", style={"color": "white", "marginRight": "8px"}),
                        dcc.Dropdown(
                            id="camp-dropdown",
                            options=[{"label": c, "value": c} for c in cleaned_data["CampName"].unique()],
                            value=cleaned_data["CampName"].unique()[0] if not cleaned_data.empty else None,
                            clearable=False,
                            style={"width": "200px", "fontSize": "14px"}
                        )
                    ], style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"}),
                    width="auto",
                    style={"marginLeft": "auto"}
                )
            ], align="center", className="w-100")
        ]
    ),
    color="#0033A0",
    dark=True
)

# ------------------ Page Layouts ------------------ #
def overview_layout():
    return dbc.Container([
        html.H2("Overview of Fire Risk Analysis", className="mt-3"),
        html.P(
            "This dashboard provides a comprehensive analysis of fire risk by integrating site-specific "
            "susceptibility data with current weather conditions. The current Fire Weather Index (FWI) is obtained "
            "using real-time weather data from wttr.in. The formula applied is:"
        ),
        html.P(
            "FWI = 0.5 * Temperature + 0.1 * Humidity + 0.3 * Wind Speed - 0.2 * Rainfall",
            style={"fontWeight": "bold"}
        ),
        html.P(
            "In addition to FWI, the Fire Susceptibility Index (FSI) and Fire Risk Index (FRI) provide further "
            "insight into local fire conditions."
        ),
        html.H4("Alternative FSI Calculation Methods", className="mt-4"),
        html.P(
            "Currently, we compute FSI by averaging four components: Environment, Fuel, Behaviour, and Response. "
            "In formula form:"
        ),
        html.P(
            "FSI = (Environment + Fuel + Behaviour + Response) / 4",
            style={"fontStyle": "italic", "marginLeft": "20px"}
        ),
        html.P(
            "However, alternative weighting schemes or additional parameters may be used. For instance:"
        ),
        html.Ul([
            html.Li("Weighted average: FSI = 0.4*Environment + 0.3*Fuel + 0.2*Behaviour + 0.1*Response."),
            html.Li("Expanded metrics: Incorporate vegetation density, topography, or local infrastructure vulnerability.")
        ]),
        html.H4("Alternative FRI Calculation Methods", className="mt-4"),
        html.P("We currently define FRI as an adjustment of FSI by FWI, using the formula:"),
        html.P(
            "FRI = FSI * (1 + (FWI / 100))",
            style={"fontStyle": "italic", "marginLeft": "20px"}
        ),
        html.P(
            "Other methods may incorporate thresholds, exponents, or additional weather factors. For example:"
        ),
        html.Ul([
            html.Li("FRI = (FSI^2) / (FWI + 1): This increases risk more dramatically when both FSI and FWI are high."),
            html.Li("FRI = FSI * (1 + α * FWI): Where α is a site-specific scaling factor based on historical data.")
        ]),
        html.H4("Severity Thresholds for FRI"),
        html.Ul([
            html.Li("Low risk: FRI < 50"),
            html.Li("Moderate risk: 50 ≤ FRI < 75"),
            html.Li("High risk: 75 ≤ FRI < 100"),
            html.Li("Extreme risk: FRI ≥ 100")
        ]),
        html.P(
            "These thresholds and formulas are preliminary and can be refined based on historical data, "
            "local conditions, and expert input."
        )
    ], fluid=True)

def site_level_layout():
    return dbc.Container([
        # Row 1: Top Indicators
        dbc.Row([
            dbc.Col(html.Div(id="site-details", className="p-3 border",
                             style={
                                 "backgroundColor": "#F8F9FA",
                                 "borderRadius": "10px",
                                 "height": "150px",
                                 "fontSize": "16px",
                                 "display": "flex",
                                 "flexDirection": "column",
                                 "justifyContent": "flex-start"
                             }),
                    width=3),
            dbc.Col(html.Div([
                # FSI Icon + Title
                html.Div([
                    html.I(className="fas fa-map-marker-alt", style={"fontSize": "24px", "marginRight": "8px"}),
                    html.H6("Site Susceptibility Index", style={"margin": 0})
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "center"}),
                html.Div(id="fsi-index", className="mt-1")
            ], className="text-center p-3 border",
               style={
                   "backgroundColor": "#F7D667",
                   "borderRadius": "10px",
                   "height": "150px",
                   "fontSize": "16px",
                   "display": "flex",
                   "flexDirection": "column",
                   "justifyContent": "center",
                   "alignItems": "center",
                   "textAlign": "center"
               }),
                    width=3),
            dbc.Col(html.Div([
                html.Div([
                    html.I(className="fas fa-thermometer-half", style={"fontSize": "24px", "marginRight": "8px"}),
                    html.H6("Fire Weather Index", style={"margin": 0})
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "center"}),
                html.Div(id="fwi-index", className="mt-1")
            ], className="text-center p-3 border",
               style={
                   "backgroundColor": "#B6E5A8",
                   "borderRadius": "10px",
                   "height": "150px",
                   "fontSize": "16px",
                   "display": "flex",
                   "flexDirection": "column",
                   "justifyContent": "center",
                   "alignItems": "center",
                   "textAlign": "center"
               }),
                    width=3),
            dbc.Col(html.Div([
                html.Div([
                    html.I(className="fas fa-exclamation-triangle", style={"fontSize": "24px", "marginRight": "8px"}),
                    html.H6("Fire Risk Index", style={"margin": 0})
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "center"}),
                html.Div(id="fri-index", className="mt-1")
            ], className="text-center p-3 border",
               style={
                   "backgroundColor": "#A0A0A0",
                   "borderRadius": "10px",
                   "height": "150px",
                   "fontSize": "16px",
                   "display": "flex",
                   "flexDirection": "column",
                   "justifyContent": "center",
                   "alignItems": "center",
                   "textAlign": "center"
               }),
                    width=3)
        ], align="center", className="mb-3"),
        html.Hr(style={"borderTop": "1px solid #ccc"}),

        # Row 2: Tabs & Graph (Left) and Narrative + Map (Right)
        dbc.Row([
            dbc.Col([
                dcc.Tabs(
                    id="site-fwi-tabs",
                    value="seasonal",
                    style={"margin": "0", "padding": "0"},
                    children=[
                        dcc.Tab(label="Seasonal", value="seasonal"),
                        dcc.Tab(label="Current", value="current"),
                        dcc.Tab(label="Forecasted", value="forecasted")
                    ]
                ),
                html.Div(
                    id="site-fwi-tabs-content",
                    className="p-3 border",
                    style={"backgroundColor": "#F8F9FA", "borderRadius": "10px", "marginTop": "10px"}
                )
            ], width=6),
            dbc.Col([
                html.Div(
                    id="site-fwi-narrative",
                    className="p-3 border",
                    style={"backgroundColor": "#F8F9FA", "borderRadius": "10px"}
                ),
                html.Br(),
                dcc.Graph(id="fire-risk-map", config={"displayModeBar": False})
            ], width=6)
        ], align="center", className="mb-3"),
        html.Hr(style={"borderTop": "1px solid #ccc"}),

        # Row 3: Dimensions Bubble Chart
        dbc.Row([
            dbc.Col(
                dcc.Graph(id="dimensions-chart", config={"displayModeBar": False}),
                width=6
            )
        ], className="mb-3"),
        html.Hr(style={"borderTop": "1px solid #ccc"}),

        # Row 4: Block-level Bar Chart and Table
        dbc.Row([
            dbc.Col(
                dcc.Graph(id="block-bar-chart", config={"displayModeBar": False}),
                width=6
            ),
            dbc.Col([
                html.H5("Fire Susceptibility Indicator Scores", className="mb-2", style={"fontWeight": "bold"}),
                dash_table.DataTable(
                    id="susceptibility-table",
                    columns=[{"name": col, "id": col} for col in ["Block", "FSI_Calculated", "FSI_Class"]],
                    data=[],  # Ensure an empty list is used if no data
                    style_table={'overflowX': 'auto'},
                    style_cell={'fontSize': '16px', 'textAlign': 'left'}
                )
            ], width=6)
        ], align="center", className="mb-3")
    ], fluid=True)

def about_layout():
    return dbc.Container([
        html.H2("Overview of Fire Risk Analysis", className="mt-3"),
        html.P(
            "This dashboard provides a comprehensive analysis of fire risk by integrating site-specific "
            "susceptibility data with current weather conditions. The current Fire Weather Index (FWI) is obtained "
            "using real-time weather data from wttr.in. The formula applied is:"
        ),
        html.P(
            "FWI = 0.5 * Temperature + 0.1 * Humidity + 0.3 * Wind Speed - 0.2 * Rainfall",
            style={"fontWeight": "bold"}
        ),
        html.P(
            "In addition to FWI, the Fire Susceptibility Index (FSI) and Fire Risk Index (FRI) provide further "
            "insight into local fire conditions."
        ),
        html.H4("Alternative FSI Calculation Methods", className="mt-4"),
        html.P(
            "Currently, we compute FSI by averaging four components: Environment, Fuel, Behaviour, and Response. "
            "In formula form:"
        ),
        html.P(
            "FSI = (Environment + Fuel + Behaviour + Response) / 4",
            style={"fontStyle": "italic", "marginLeft": "20px"}
        ),
        html.P(
            "However, alternative weighting schemes or additional parameters may be used. For instance:"
        ),
        html.Ul([
            html.Li("Weighted average: FSI = 0.4*Environment + 0.3*Fuel + 0.2*Behaviour + 0.1*Response."),
            html.Li("Expanded metrics: Incorporate vegetation density, topography, or local infrastructure vulnerability.")
        ]),
        html.H4("Alternative FRI Calculation Methods", className="mt-4"),
        html.P("We currently define FRI as an adjustment of FSI by FWI, using the formula:"),
        html.P(
            "FRI = FSI * (1 + (FWI / 100))",
            style={"fontStyle": "italic", "marginLeft": "20px"}
        ),
        html.P(
            "Other methods may incorporate thresholds, exponents, or additional weather factors. For example:"
        ),
        html.Ul([
            html.Li("FRI = (FSI^2) / (FWI + 1): This increases risk more dramatically when both FSI and FWI are high."),
            html.Li("FRI = FSI * (1 + α * FWI): Where α is a site-specific scaling factor based on historical data.")
        ]),
        html.H4("Severity Thresholds for FRI"),
        html.Ul([
            html.Li("Low risk: FRI < 50"),
            html.Li("Moderate risk: 50 ≤ FRI < 75"),
            html.Li("High risk: 75 ≤ FRI < 100"),
            html.Li("Extreme risk: FRI ≥ 100")
        ]),
        html.P(
            "These thresholds and formulas are preliminary and can be refined based on historical data, "
            "local conditions, and expert input."
        )
    ], fluid=True)

# ------------------ Main App Layout ------------------ #
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    navbar,
    html.Hr(style={"margin": "0", "padding": "0", "borderTop": "1px solid #ccc"}),  # Line after Navbar
    dcc.Tabs(id="fwi-tabs", value="seasonal", style={"display": "none"}),
    html.Div(id="page-content")
])

# ------------------ Multi-Page Navigation Callback ------------------ #
@app.callback(Output("page-content", "children"),
              [Input("url", "pathname")])
def display_page(pathname):
    if pathname == "/about":
        return about_layout()
    elif pathname == "/overview":
        return overview_layout()
    return site_level_layout()

# ------------------ Overview Tab Callback ------------------ #
@app.callback(
    Output("overview-tab-content", "children"),
    [Input("camp-dropdown", "value"),
     Input("url", "pathname")]
)
def render_overview_tab(selected_camp, pathname):
    if pathname != "/overview":
        return dash.no_update
    return html.Div("This page now serves as a high-level summary of the dashboard. Please navigate to the Site Level page for detailed FWI analysis.")

# ------------------ Site Level FWI Tab Callback ------------------ #
@app.callback(
    [Output("site-fwi-tabs-content", "children"),
     Output("site-fwi-narrative", "children")],
    [Input("camp-dropdown", "value"),
     Input("site-fwi-tabs", "value")]
)
def render_site_fwi_tab(selected_camp, active_tab):
    row = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update, dash.no_update
    
    lat = row.iloc[0]["Latitude"]
    lon = row.iloc[0]["Longitude"]

    # For the 5-Year FWI Trend, use the previous year and count down 5 years.
    previous_year = datetime.now().year - 1
    if active_tab == "seasonal":
        years = sorted([previous_year - i for i in range(5)])  # ascending order
        year_labels = [str(y) for y in years]
        yearly_fwi = []
        for y in years:
            monthly_vals = get_monthly_fwi_nasa(lat, lon, year=y)
            avg_fwi = sum(monthly_vals) / len(monthly_vals)
            yearly_fwi.append(math.ceil(avg_fwi))
        fig = px.line(
            x=year_labels,
            y=yearly_fwi,
            labels={"x": "Year", "y": "Average FWI"},
            title=f"5-Year FWI Trend (Camp {selected_camp})"
        )
        fig.update_traces(mode='lines+markers+text', text=[str(val) for val in yearly_fwi], textposition='top center')
        max_fwi = max(yearly_fwi)
        min_fwi = min(yearly_fwi)
        max_year = year_labels[yearly_fwi.index(max_fwi)]
        min_year = year_labels[yearly_fwi.index(min_fwi)]
        narrative_text = html.Div([
            html.H5("5-Year FWI Trend Narrative", style={"fontWeight": "bold"}),
            html.P(
                f"From {year_labels[0]} to {year_labels[-1]}, Camp {selected_camp} had FWI values "
                f"ranging from {min_fwi} in {min_year} to {max_fwi} in {max_year}. A higher FWI indicates drier conditions and greater fire risk."
            )
        ])
        return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": "100%"}), narrative_text

    elif active_tab == "current":
        current_year = datetime.now().year
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        monthly_vals = get_monthly_fwi_nasa(lat, lon, year=current_year)
        monthly_vals = [math.ceil(val) for val in monthly_vals]
        fig = px.line(
            x=months,
            y=monthly_vals,
            labels={"x": "Month", "y": "FWI"},
            title=f"Current Year ({current_year}) Monthly FWI (Camp {selected_camp})"
        )
        fig.update_traces(mode="lines+markers")
        narrative_text = html.Div([
            html.H5("Current Year Monthly FWI Narrative", style={"fontWeight": "bold"}),
            html.P(
                f"In {current_year}, the monthly FWI values for Camp {selected_camp} were: " +
                ", ".join([f"{m}: {v}" for m, v in zip(months, monthly_vals)]) +
                ". These values provide insight into the month-to-month fire weather conditions."
            )
        ])
        return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": "100%"}), narrative_text

    elif active_tab == "forecasted":
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        data = []
        for m in range(1, 13):
            fwi_val = np.random.randint(0, 36)
            data.append({"Month": month_names[m-1], "FWI": fwi_val})
        df_fc = pd.DataFrame(data)
        fig = px.line(
            df_fc,
            x="Month",
            y="FWI",
            title=f"Forecasted FWI (2026) - {selected_camp}"
        )
        fig.update_traces(mode="lines+markers")
        narrative_text = html.Div([
            html.H5("Forecasted FWI Narrative", style={"fontWeight": "bold"}),
            html.P(
                f"Forecasted FWI values for 2026 are generated as placeholder data for Camp {selected_camp}. "
                "These values help in planning and preparedness, though they are subject to change with actual weather conditions."
            )
        ])
        return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": "100%"}), narrative_text

    return html.Div("Select a tab to view FWI data."), html.Div("")

# ------------------ Site Level Dashboard Update Callback ------------------ #
@app.callback(
    [
        Output("site-details", "children"),
        Output("fsi-index", "children"),
        Output("fwi-index", "children"),
        Output("fri-index", "children"),
        Output("block-bar-chart", "figure"),
        Output("fire-risk-map", "figure"),
        Output("susceptibility-table", "data"),
        Output("dimensions-chart", "figure")
    ],
    [Input("camp-dropdown", "value")]
)
def update_dashboard(selected_camp):
    camp_data = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if camp_data.empty:
        return ("No data available", "-", "-", "-",
                {}, {}, [], {})
    
    site_container = html.Div([
        html.H5("Site Details", style={"fontWeight": "bold", "fontSize": "18px"}),
        html.P([html.Strong("Site name: "), selected_camp]),
        html.P([html.Strong("Assessment date: "), "2024-09-25"]),
        html.P([html.Strong("Site population: "), "33,515"])
    ], style={"fontSize": "14px"})
    
    fsi_value = math.ceil(round(camp_data["FSI_Calculated"].mean(), 1))
    fsi_class = classify_fsi(fsi_value)
    # Get means for breakdown
    env_val = math.ceil(round(camp_data["Environment"].mean(), 1))
    fuel_val = math.ceil(round(camp_data["Fuel"].mean(), 1))
    beh_val = math.ceil(round(camp_data["Behaviour"].mean(), 1))
    resp_val = math.ceil(round(camp_data["Response"].mean(), 1))
    
    lat = camp_data.iloc[0]["Latitude"]
    lon = camp_data.iloc[0]["Longitude"]
    fwi_value = math.ceil(get_fwi_standard(lat, lon))
    fri_value = math.ceil(round(fsi_value * (1 + (fwi_value / 100)), 2))
    
    fsi_text = html.Div([
        html.H2(f"{fsi_value} - {fsi_class}", className="mt-1 mb-0", style={"display": "inline-block"}),
        html.P(f"(Environment: {env_val} + Fuel: {fuel_val} + Behaviour: {beh_val} + Response: {resp_val}) / 4",
               style={"fontSize": "14px", "margin": "0", "color": "#555"})
    ])
    
    raw_weather = get_wttr_data(lat, lon)
    weather_details = (f"Temp_c: {raw_weather['temp']}°C; "
                       f"Humidity: {raw_weather['humidity']}%; "
                       f"WindSpeedKmph: {raw_weather['windspeed']} km/h; "
                       f"precipMM: {raw_weather['precip']} mm")
    
    fwi_text = html.Div([
        html.H2(f"{fwi_value} - {categorize_fwi(fwi_value).split()[0]}", className="mt-1 mb-0", style={"display": "inline-block"}),
        html.P(weather_details, style={"fontSize": "14px", "margin": "0"}),
        html.P(f"Last update: Time: {raw_weather['local_time']}", style={"fontSize": "14px", "margin": "0", "color": "#555"})
    ])
    
    fri_text = html.Div([
        html.H2(f"{fri_value} - {short_categorize_fri(fri_value)}", className="mt-1 mb-0", style={"display": "inline-block"}),
        html.P(f"FRI = FSI * (1 + (FWI/100)) = {fsi_value} * (1 + ({fwi_value}/100))", style={"fontSize": "14px", "margin": "0"}),
        html.P(f"FRI Severity: {categorize_fri(fri_value)}", style={"fontSize": "14px", "margin": "0", "color": "#555"})
    ])
    
    block_means = camp_data.groupby("Block")[["Environment", "Fuel", "Behaviour", "Response"]].mean().reset_index()
    melted = block_means.melt(id_vars="Block", var_name="Dimension", value_name="Score")
    melted["Score"] = melted["Score"].round(0).astype(int)
    block_bar_fig = px.bar(
        melted,
        x="Block",
        y="Score",
        color="Dimension",
        barmode="group",
        title="Susceptibility Dimension Score by Block",
        text="Score"
    )
    block_bar_fig.update_traces(texttemplate='%{text}', textposition='outside')
    
    map_fig = px.scatter_mapbox(
        camp_data,
        lat="Latitude",
        lon="Longitude",
        color="FSI_Calculated",
        size="FSI_Calculated",
        hover_name="CampName",
        mapbox_style="carto-positron",
        zoom=10,
        title="Camp Fire Susceptibility"
    )
    
    table_data = camp_data[["Block", "FSI_Calculated", "FSI_Class"]].to_dict("records")
    
    dimensions_fig = create_fsi_dimensions_figure(camp_data)
    
    return (
        site_container,
        fsi_text,
        fwi_text,
        fri_text,
        block_bar_fig,
        map_fig,
        table_data,
        dimensions_fig
    )

if __name__ == '__main__':
    app.run(debug=True)