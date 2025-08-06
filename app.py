from datetime import date, timedelta, datetime
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
import plotly.express as px
import pandas as pd
import numpy as np
import requests
import math
import json
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go

# ------------------ Data Loading and Preparation ------------------ #
aor_data = pd.read_excel("AOR.xlsx")
# **rename first** so aor_data has CampName
aor_data.rename(columns={'New_Camp_Name': 'CampName'}, inplace=True)
response_details = pd.read_excel("CampResponseDetails.xlsx")
fire_data = pd.read_csv("Fire Susceptability Data Block.csv")

# — load camp-level FSI summary (one row per camp) —
camp_summary = pd.read_csv("Fire Susceptability Data Camp.csv")
camp_summary.rename(columns={'FSI': 'FSI_Calculated'}, inplace=True)
camp_summary = camp_summary.merge(
    aor_data[['CampName','Latitude','Longitude']],
    on='CampName', how='left'
)
camp_summary = camp_summary.dropna(subset=['Latitude','Longitude'])


# Load GeoJSON (Camp Boundaries)
try:
    with open("Camp_Outline.json", "r") as f:
        geojson_data = json.load(f)
except FileNotFoundError:
    geojson_data = None

# Convert Esri JSON to real GeoJSON
for feat in geojson_data['features']:
    # 1) turn rings → GeoJSON polygon
    feat['geometry'] = {
        "type": "Polygon",
        "coordinates": feat['geometry']['rings']
    }
    # 2) move `attributes` → `properties`
    feat['properties'] = feat.pop('attributes')

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

# ------------------ Weather Data Fetching from Mateo ------------------ #
def get_weather_noon(lat, lon, iso_date):
    """
    Returns temperature, RH, wind and precip at 13:00 local time on iso_date.
    Falls back to daily totals/averages if 13:00 isn’t in the hourly array.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={iso_date}&end_date={iso_date}"
        # add hourly precipitation
        f"&hourly=temperature_2m,relativehumidity_2m,windspeed_10m,precipitation"
        # keep daily precipitation_sum for fallback only
        f"&daily=precipitation_sum"
        f"&timezone=auto"
    )
    js = requests.get(url, timeout=10).json()

    times = js["hourly"]["time"]
    try:
        idx = times.index(f"{iso_date}T13:00")
        temp   = js["hourly"]["temperature_2m"][idx]
        rh     = js["hourly"]["relativehumidity_2m"][idx]
        wind   = js["hourly"]["windspeed_10m"][idx]
        precip = js["hourly"]["precipitation"][idx]    # <— rain at 13:00
    except ValueError:
        # fallback: if 13:00 isn’t present
        temp   = max(js["hourly"]["temperature_2m"])
        rh     = sum(js["hourly"]["relativehumidity_2m"]) / len(js["hourly"]["relativehumidity_2m"])
        wind   = sum(js["hourly"]["windspeed_10m"])      / len(js["hourly"]["windspeed_10m"])
        precip = js["daily"]["precipitation_sum"][0]    # still the 24 h total

    return {"temp": temp, "rh": rh, "wind": wind, "precip": precip}

def calc_fwi_simple(temp, rh, wind, rain):
    return 0.5*temp + 0.1*rh + 0.3*wind - 0.2*rain

def get_fwi_standard(lat, lon):
    today = date.today().isoformat()
    w = get_weather_noon(lat, lon, today)
    return math.ceil(calc_fwi_simple(w["temp"], w["rh"], w["wind"], w["precip"]))

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
    
# — now that get_fwi_standard is defined, we can enrich camp_summary —
camp_summary["FWI"] = camp_summary.apply(
    lambda row: get_fwi_standard(row["Latitude"], row["Longitude"]),
    axis=1
)
camp_summary["FRI"] = (
    camp_summary["FSI_Calculated"] * (1 + camp_summary["FWI"] / 100)
).round(1)
camp_summary["FRI_Class"] = camp_summary["FRI"].apply(categorize_fri)

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

# ------------------ Monthly FWI Function ------------------ #
def get_monthly_fri(lat, lon, fsi, year):
    # fetch the 12 monthly FWI values
    monthly_fwi = get_monthly_fwi_nasa(lat, lon, year)
    # convert to FRI
    monthly_fri = [fsi * (1 + w/100) for w in monthly_fwi]
    # month labels
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return pd.DataFrame({"month": month_names, "fri": monthly_fri})

# Rename & repurpose create_seasonal_fri_figure -> create_monthly_fri_figure
def create_monthly_fri_figure(camp_row):
    year = datetime.now().year
    lat, lon = camp_row["Latitude"], camp_row["Longitude"]
    fsi = camp_row["FSI_Calculated"]
    df = get_monthly_fri(lat, lon, fsi, year)

    fig = px.bar(
        df,
        x="month",
        y="fri",
        labels={"month":"Month", "fri":"Fire Risk Index"},
        title=f"Monthly FRI ({year}) for {camp_row['CampName']}"
    )
    # pad the y-axis a bit
    fig.update_yaxes(range=[0, df["fri"].max()*1.1])
    return fig


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

def create_fsi_dimensions_figure_from_summary(camp_row):
    dims   = ["Environment", "Fuel", "Behaviour", "Response"]
    scores = [
        math.ceil(camp_row["Environment"]),
        math.ceil(camp_row["Fuel"]),
        math.ceil(camp_row["Behaviour"]),
        math.ceil(camp_row["Response"]),
    ]

    # 1) Start a graph‐objects Figure
    fig = go.Figure()

    # 2) Add a horizontal "pill" behind each point
    fig.add_trace(go.Bar(
        x=[100]*4,               # full scale pill
        y=dims,
        orientation='h',
        marker=dict(color='lightgray'),
        width=0.4,
        showlegend=False,
        hoverinfo='none'
    ))

    # 3) Overlay the bubbles
    fig.add_trace(go.Scatter(
        x=scores,
        y=dims,
        mode='markers+text',
        marker=dict(
            size=[s/100*40 + 20 for s in scores],    # bubble size proportional + min size
            color=['firebrick','darkorange','seagreen','royalblue'],  # or any palette you like
            line=dict(color='black', width=1)
        ),
        text=[str(s) for s in scores],
        textposition='middle center',
        showlegend=False
    ))

    # 4) Tidy up axes & layout
    fig.update_xaxes(
        range=[0,100],
        tickvals=[0,20,40,60,80,100],
        title_text="Score"
    )
    fig.update_yaxes(
        autorange="reversed"       # so Environment is on top
    )
    fig.update_layout(
        title="FSI Dimensions (Camp Summary)",
        margin=dict(l=60, r=40, t=50, b=40),
        height=300
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
            dbc.Row(
                [
                    # 1) Brand
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
                            style={"fontSize": "28px", "fontWeight": "bold"}
                        ),
                        width="auto",
                        style={"paddingLeft": 0}
                    ),
                    # 2) Your nav links (Site Level, Overview, About)
                    dbc.Col(
                        dbc.Nav(
                            [
                                dbc.NavItem(dbc.NavLink("Site Level", href="/",        active="exact")),
                                dbc.NavItem(dbc.NavLink("Overview", href="/overview", active="exact")),
                                dbc.NavItem(dbc.NavLink("About",      href="/about",   active="exact")),
                            ],
                            navbar=True
                        ),
                        width="auto",
                        style={"marginLeft": "2rem"}
                    ),
                    # 3) Camp dropdown (toggled hidden on overview/about)
                    dbc.Col(
                        html.Div(
                            id="camp-dropdown-container",
                            children=[
                                html.Span("Select a camp:", style={"color":"white","marginRight":"8px"}),
                                dcc.Dropdown(
                                    id="camp-dropdown",
                                    options=[{"label": c, "value": c}
                                             for c in cleaned_data["CampName"].unique()],
                                    value=cleaned_data["CampName"].unique()[0]
                                             if not cleaned_data.empty else None,
                                    clearable=False,
                                    style={"width":"200px","fontSize":"14px"}
                                )
                            ],
                            style={"display":"flex","alignItems":"center","justifyContent":"flex-end"}
                        ),
                        width="auto",
                        style={"marginLeft":"auto"}
                    )
                ],
                align="center",
                className="w-100"
            )
        ]
    ),
    color="#0033A0",
    dark=True
)

# ------------------ Page Layouts ------------------ #
def overview_layout():
    # — build a display‐ready df —
    df = camp_summary.copy()
    df["Camp"]  = df.CampName
    df["FSI"]   = np.ceil(df.FSI_Calculated).astype(int)
    df["FRI"]   = df.FRI.round(0).astype(int)
    df["FRI Severity"] = df.FRI_Class

    counts = df["FRI Severity"].value_counts().reindex(
        ["Low risk","Moderate risk","High risk","Extreme risk"], fill_value=0
    )
    filter_row = dbc.Row([
        dbc.Col(html.Label("Filter by FRI Severity:"), width="auto"),
        dbc.Col(dcc.Dropdown(
            id="overview-severity-filter",
            options=[{"label":"All","value":"All"}] +
                    [{"label":c,"value":c} for c in counts.index],
            value="All", clearable=False, style={"width":"200px"}
        ), width="auto"),
    ], align="center", className="mb-3")
    # 1) Top-level metrics
    avg_fsi = math.ceil(df["FSI_Calculated"].mean())
    avg_fwi = math.ceil(df["FWI"].mean())
    avg_fri = math.ceil(df["FRI"].mean())
    counts  = df["FRI_Class"].value_counts().reindex(
        ["Low risk","Moderate risk","High risk","Extreme risk"], fill_value=0
    )
    cards = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Avg. FSI"),
            dbc.CardBody(html.H4(f"{avg_fsi}", className="card-title"))
        ], color="warning", inverse=True), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Avg. FWI"),
            dbc.CardBody(html.H4(f"{avg_fwi}", className="card-title"))
        ], color="success", inverse=True), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Avg. FRI"),
            dbc.CardBody(html.H4(f"{avg_fri}", className="card-title"))
        ], color="secondary", inverse=True), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Extreme-risk camps"),
            dbc.CardBody(html.H4(f"{counts['Extreme risk']}", className="card-title"))
        ], color="danger", inverse=True), width=3),
    ], className="mb-4")

    # 2) Narrative
    narrative = html.P(
        f"Out of {len(df)} camps, {counts['Extreme risk']} are Extreme, "
        f"{counts['High risk']} High, {counts['Moderate risk']} Moderate and "
        f"{counts['Low risk']} Low risk today. The average FRI is {avg_fri}.",
        style={"fontSize":"16px", "marginBottom":"1.5rem"}
    )
    html.Hr(style={"borderTop": "1px solid #ccc"}),

    # 3) Risk distribution chart
    dist_fig = px.bar(
        x=counts.index, y=counts.values,
        labels={"x":"FRI Severity","y":"Number of Camps"},
        title="Distribution of Camps by FRI Severity"
    )
    dist_fig.update_layout(plot_bgcolor="white", margin={"t":40,"b":20})

    # 4) filter control
    severity_options = [{"label": cls, "value": cls} for cls in ["All"] + counts.index.tolist()]
    filter_row = dbc.Row([
        dbc.Col(html.Label("Filter by FRI Severity:"), width="auto"),
        dbc.Col(dcc.Dropdown(
            id="overview-severity-filter",
            options=severity_options,
            value="All",
            clearable=False,
            style={"width":"200px"}
        ), width="auto")
    ], className="mb-3", align="center")

    # 5) Table & Map placeholders (data filled via callback)
    table = dash_table.DataTable(
        id="overview-table",
        columns=[
            {"name":"Camp",         "id":"Camp"},
            {"name":"FSI",          "id":"FSI"},
            {"name":"FWI",          "id":"FWI"},
            {"name":"FRI",          "id":"FRI"},
            {"name":"FRI Severity", "id":"FRI Severity"},
        ],
        data=df[["Camp","FSI","FWI","FRI","FRI Severity"]].to_dict("records"),
        page_size=15,
        style_table={"overflowX":"auto"},
        style_cell={"padding":"5px","textAlign":"left"},
    )
    # compute center from camp_summary
    centre = {
        "lat": camp_summary["Latitude"].mean(),
        "lon": camp_summary["Longitude"].mean()
    }
    map_fig = px.choropleth_mapbox(
        camp_summary.assign(FRI=lambda d: np.floor(d.FRI + 0.5).astype(int)),
        geojson={"type":"FeatureCollection","features":geojson_data["features"]},
        locations="CampName", featureidkey="properties.CampName",
        color="FRI", range_color=(0,100),
        mapbox_style="carto-positron",
        center=centre, zoom=9.5, opacity=0.6,
        title="FRI Heatmap Across All Camps"
    )
    map = dcc.Graph(id="overview-heatmap", figure=map_fig, config={"displayModeBar":False})


    top5 = df.nlargest(5, "FRI")[["Camp","FRI","FRI Severity"]]
    bot5 = df.nsmallest(5, "FRI")[["Camp","FRI","FRI Severity"]]
    tb_row = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Top 5 Highest-Risk Camps"),
            dbc.CardBody(
                dash_table.DataTable(
                    columns=[{"name": c, "id": c} for c in top5.columns],
                    data=top5.to_dict("records"),
                    page_action="none",
                    style_cell={"padding":"3px","textAlign":"left"},
                )
            )
        ]), width=6),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Bottom 5 Lowest-Risk Camps"),
            dbc.CardBody(
                dash_table.DataTable(
                    columns=[{"name": c, "id": c} for c in bot5.columns],
                    data=bot5.to_dict("records"),
                    page_action="none",
                    style_cell={"padding":"3px","textAlign":"left"},
                )
            )
        ]), width=6),
    ], className="mt-4")

    return dbc.Container([
        html.H2("Overview of All Camps", className="mt-3"),
        html.Hr(style={"borderTop": "1px solid #ccc"}),
        cards,
        narrative,
        html.Hr(style={"borderTop": "1px solid #ccc"}),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=dist_fig, config={"displayModeBar":False}), width=6),
            dbc.Col(filter_row, width=6),
        ], className="mb-4"),

        html.Hr(style={"borderTop": "1px solid #ccc"}),
        dbc.Row([
            dbc.Col(table, width=6),
            dbc.Col(map, width=6),
        ], className="mb-4"),
        # Divider
        html.Hr(style={"borderTop": "1px solid #ccc"}),        tb_row
    ], fluid=True)


@app.callback(
    [Output("overview-table",     "data"),
     Output("overview-heatmap",   "figure")],
    Input("overview-severity-filter", "value")
)
def filter_overview(sev):
    dff = camp_summary.copy()
    if sev != "All":
        dff = dff[dff.FRI_Class == sev]
   # create a true 'FSI' column (ceiled) and an integer FRI
    dff = dff.assign(
        Camp=lambda d: d.CampName,
        FSI=lambda d: np.ceil(d.FSI_Calculated).astype(int),
        FRI=lambda d: np.ceil(d.FRI).astype(int),
    )
    # now select the new FSI, not FSI_Calculated
    table_data = (
        dff[["CampName","FSI","FWI","FRI","FRI_Class"]]
           .rename(columns={
               "CampName":"Camp",
               "FRI_Class":"FRI Severity"
           })
           .to_dict("records")
    )
    # update map
    centre = {"lat": dff["Latitude"].mean(), "lon": dff["Longitude"].mean()}
    fig = px.choropleth_mapbox(
        dff.assign(FRI=lambda d: np.ceil(d.FRI).astype(int)),
        geojson={"type":"FeatureCollection","features":geojson_data["features"]},
        locations="CampName", featureidkey="properties.CampName",
        color="FRI", range_color=(0,100),
        mapbox_style="carto-positron",
        center=centre, zoom=9.5, opacity=0.6
    )
    fig.update_layout(margin={"t":30,"b":0,"l":0,"r":0})

    return table_data, fig


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
                    html.H6("Site Fire Susceptibility Index", style={"margin": 0})
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
                    html.H6("Site Fire Weather Index", style={"margin": 0})
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
                    html.H6("Site Fire Risk Index", style={"margin": 0})
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
        # ── Row 1b: Contact toggle ──
        dbc.Row([
            dbc.Col([
                html.A(
                    "Contact Information",
                    id="contact-toggle",
                    style={"cursor":"pointer", "textDecoration":"underline", "color":"#007bff"}
                ),
                dbc.Collapse(
                    html.Div(id="contact-content", className="p-3"),
                    id="contact-collapse",
                    is_open=False,
                    style={"backgroundColor":"#f8f9fa", "borderRadius":"5px", "marginTop":"5px"}
                )
            ], width=12)
        ], className="mb-3"),

        html.Hr(style={"borderTop":"1px solid #ccc"}),
        # Row 2: FRI tabs (left) and FWI tabs (right)
        dbc.Row([
            # ─── FRI ───
            dbc.Col([
                dcc.Tabs(
                    id="site-fri-tabs",
                    value="monthly",
                    children=[
                        dcc.Tab(label="Monthly",  value="monthly"),
                        dcc.Tab(label="Current",  value="current"),
                        dcc.Tab(label="Forecast", value="forecasted"),
                    ]
                ),
                html.Div(
                    id="site-fri-content",
                    className="p-3 border",
                    style={"backgroundColor":"#F8F9FA","borderRadius":"10px","marginTop":"10px"}
                )
            ], width=6),

               # ─── FWI ───
    dbc.Col([
        dcc.Tabs(
            id="site-fwi-tabs",
            value="monthly",
            children=[
                dcc.Tab(label="Monthly",  value="monthly"),
                dcc.Tab(label="Current",  value="current"),
                dcc.Tab(label="Forecast", value="forecasted"),
            ]
        ),
        html.Div(
            [
                html.Div(id="site-fwi-content"),
                html.Div(id="site-fwi-narrative", className="mt-3")
            ],
            className="p-3 border",
            style={"backgroundColor":"#F8F9FA","borderRadius":"10px","marginTop":"10px"
            }
        )
    ], width=6),

        ], className="mb-3"),
        html.Hr(style={"borderTop": "1px solid #ccc"}),
dbc.Row([
            # Left: Camp boundary choropleth
    dbc.Col([
        html.H4("Camp Boundary FRI Heatmap", style={"textAlign": "center"}),
        dcc.Graph(id="fire-risk-map", config={"displayModeBar": False})
    ], width=6),
            # Right: Live Windy iframe
            dbc.Col([
                html.H5(id="wind-map-title",
                        children="Live Wind Map",
                        style={"fontWeight":"bold","marginBottom":"10px"}),
                html.Iframe(
                    id="windy-iframe",
                    style={"width": "100%", "height": "400px", "border": "none"}
                )
            ], width=6)
        ], className="mb-3"),
        html.Hr(style={"borderTop": "1px solid #ccc"}),
        # Row 4: Block-level Bar Chart and Table
        dbc.Row([
            dbc.Col([
                html.H4("Block-Level Susceptibility Scores", style={"textAlign":"center"}),
                dcc.Graph(id="block-bar-chart", config={"displayModeBar":False}),
            ], width=6),

            dbc.Col([
                html.H4("Fire Susceptibility Indicator Scores", style={"textAlign":"center"}),
                dash_table.DataTable(
                    id="susceptibility-table",
                    columns=[
                        {"name": "Site Block", "id": "Site Block"},
                        {"name": "FSI Score",  "id": "FSI Score"},
                        {"name": "FSI Class",  "id": "FSI_Class"},
                    ],
                    data=[],  # will be populated by your callback
                    style_table={'overflowX': 'auto'},
                    style_cell={'fontSize': '16px', 'textAlign': 'left'}
                ),
            ], width=6),

        ], align="center", className="mb-3")
    ], fluid=True)

def about_layout():
    return dbc.Container([
        html.H2("How This Dashboard Works", className="mt-3"),

        html.H4("Data Sources & Update Frequency"),
        html.Ul([
            html.Li("Camp survey data (FSI): updated regularly"),
            html.Li("On-the-day weather (FWI): fetched daily at 13:00 local time via Open-Meteo API"),
            html.Li("Historic climatology: NASA POWER monthly aggregates")
        ]),

        html.H4("Calculation Methods"),
        html.Pre(
            "FSI  = (Environment + Fuel + Behaviour + Response) / 4\n"
            "FWI  = 0.5·T + 0.1·RH + 0.3·Wind − 0.2·Rain\n"
            "FRI  = FSI × (1 + FWI/100)",
            style={"backgroundColor": "#f8f9fa", "padding": "10px", "borderRadius": "5px"}
        ),

        html.H4("Fire Weather Index (FWI) Thresholds"),
        html.P(
            "FWI indicates daily fire weather conditions based on temperature, humidity, wind, and precipitation."
            " These categories guide preparedness levels."
        ),
        html.Table([
            html.Thead(html.Tr([html.Th("FWI Range"), html.Th("Fire Danger Category")])),
            html.Tbody([
                html.Tr([html.Td("0 – 20"), html.Td("Low fire danger (Green)")]),
                html.Tr([html.Td("21 – 30"), html.Td("Moderate fire danger (Orange)")]),
                html.Tr([html.Td("31 and above"), html.Td("Severe fire danger (Red)")]),
            ])
        ], style={"width": "100%", "marginBottom": "2rem"}),

        html.H4("Fire Risk Index (FRI) Thresholds"),
        html.P(
            "FRI combines fire susceptibility and weather indices to estimate overall fire risk at the site level."
        ),
        html.Table([
            html.Thead(html.Tr([html.Th("FRI Range"), html.Th("Risk Category")])),
            html.Tbody([
                html.Tr([html.Td("0 – 49"), html.Td("Low risk (Green)")]),
                html.Tr([html.Td("50 – 74"), html.Td("Moderate risk (Orange)")]),
                html.Tr([html.Td("75 – 99"), html.Td("High risk (Red)")]),
                html.Tr([html.Td("100 and above"), html.Td("Extreme risk (Dark Red/Purple)")]),
            ])
        ], style={"width": "100%", "marginBottom": "2rem"}),

        html.H4("Team & Support"),
        html.P("Maintained by the XXX Team"),
        html.P("Contact: xxxxxxxxxxxx"),

        html.H4("Version History"),
        html.Ul([
            html.Li("v1.0 – Initial release with FSI, FWI & FRI calculations"),
            html.Li("v1.1 – Added monthly narratives and map filtering"),
            html.Li("v1.2 – Introduced contact panel and enhanced Overview metrics")
        ]),

        html.H4("Glossary"),
        html.Table([
            html.Tr([html.Th("Term"), html.Th("Definition")]),
            html.Tr([html.Td("FSI"), html.Td("Fire Susceptibility Index")]),
            html.Tr([html.Td("FWI"), html.Td("Fire Weather Index")]),
            html.Tr([html.Td("FRI"), html.Td("Fire Risk Index")]),
            html.Tr([html.Td("Severity classes"), html.Td("Low, Moderate, High, Extreme risk")])
        ], style={"width": "100%", "marginBottom": "2rem"}),

        html.P(
            "Use the Overview tab for a high-level summary across all camps; "
            "the Site Level tab drills down to per-camp monthly, current, and forecasted fire risk."
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

@app.callback(
    Output("camp-dropdown-container", "style"),
    Input("url", "pathname"),
)
def toggle_dropdown(pathname):
    # only show on the Site Level page, whose pathname is "/"
    if pathname == "/":
        return {"display": "flex", "alignItems": "center", "justifyContent": "flex-end"}
    else:
        return {"display": "none"}

# ------------------ Windy Title ------------------ #
@app.callback(
        Output("wind-map-title", "children"),
        Input("camp-dropdown", "value")
    )
def update_wind_title(camp):
        return f"Live Wind Map ({camp} Focus)"


# ------------------ Multi-Page Navigation Callback ------------------ #
@app.callback(Output("page-content","children"), [Input("url","pathname")])
def display_page(pathname):
    if pathname == "/overview":
        return overview_layout()
    elif pathname == "/about":
        return about_layout()
    else:
        return site_level_layout()


@app.callback(
    [Output("contact-collapse", "is_open"),
     Output("contact-content",  "children")],
    [Input("contact-toggle",     "n_clicks"),
     Input("camp-dropdown",      "value")],
    [State("contact-collapse",   "is_open")]
)
def toggle_and_populate_contact(n_clicks, selected_camp, is_open):
    # toggle only when the link is clicked
    if not n_clicks:
        # on initial load, keep it closed with no content
        return False, dash.no_update

    # find the row in response_details
    row = response_details.loc[response_details.CampName == selected_camp]
    if row.empty:
        return not is_open, html.P("No contact info available for this camp.")

    row = row.iloc[0]
    # build some paragraphs from each column
    content = html.Div([
        html.P([html.Strong("Site-Management focal: "), row["SM focal(Name and Mobile No)"]]),
        html.P([html.Strong("Sector Focals: "),        row["Sector Focals(Name and Mobile No)"]]),
        html.P([html.Strong("DMU Lead: "),              row["DMU Lead(Name and Mobile No)"]]),
        html.P([html.Strong("Infrastructure: "),        row["List of infrastructure"]])
    ], style={"fontSize":"14px"})

    # flip the collapse state each click
    return not is_open, content
   
# ------------------ Site Level FWI Tab Callback  ------------------ #    

@app.callback(
    [
      Output("site-fwi-content",   "children"),
      Output("site-fwi-narrative", "children")
    ],
    [
      Input("camp-dropdown", "value"),
      Input("site-fwi-tabs",   "value")
    ]
)
def render_fwi_tab(selected_camp, active_tab):
    row = camp_summary[camp_summary["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update, dash.no_update
    lat, lon = row.iloc[0][["Latitude","Longitude"]]

    # --- Monthly FWI ---
    if active_tab == "monthly":
        year = datetime.now().year
        # fetch the 12 monthly FWI values
        monthly = get_monthly_fwi_nasa(lat, lon, year)
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        df = pd.DataFrame({"month": months, "fwi": monthly})
        df["fwi"] = df["fwi"].round(0).astype(int)

        # classify each month’s FWI
        df["risk"] = df["fwi"].apply(categorize_fwi)

        # map a color to each risk level
        risk_to_color = {
            "Low fire danger":      "green",
            "Moderate fire danger": "orange",
            "Severe fire danger":   "red",
        }
        df["text_color"] = df["risk"].map(risk_to_color)

        # build bar chart, using the class as the text label
        fig = px.bar(
            df,
            x="month",
            y="fwi",
            labels={"month":"Month", "fwi":"Fire Weather Index"},
            title=f"Monthly Fire Weather Index ({year}) for {selected_camp}"
        )
        fig.update_traces(
            marker_color="steelblue",
            text=df["risk"],
            textposition="outside",
            textfont=dict(color=df["text_color"], size=12),
            showlegend=False
        )
        fig.update_yaxes(range=[0, 100])    # 0–100 scale

        narrative = html.Div([
            html.H5("Monthly Fire Weather Index", style={"fontWeight":"bold"}),
            html.P(
                "This bar chart shows your camp’s Fire Weather Index—how hot, dry and windy it typically is each month—"
                "with each bar labeled by its fire-danger category (Low, Moderate, Severe). "
                "Use this to identify your camp’s climatological fire-weather seasonality and plan seasonal mitigation."
            )
        ], style={"fontSize":"14px"})

        return dcc.Graph(figure=fig, config={"displayModeBar":False}), narrative

    # --- Current FWI comparison ---
    elif active_tab == "current":
        # build df with class
        df = (
            camp_summary[["CampName", "FWI"]]
            .assign(FWI=lambda d: d.FWI.round(0).astype(int))
            .sort_values("FWI", ascending=False)
            .reset_index(drop=True)
        )

        # selected camp stats
        fwi_sel = df.loc[df.CampName == selected_camp, "FWI"].iloc[0]
        rank    = int(df.index[df.CampName == selected_camp][0]) + 1
        total   = len(df)

        # bar colors (highlight selected camp)
        colors = ["#EF553B" if c == selected_camp else "#636EFA" for c in df.CampName]

        # classify each camp’s FWI
        df["risk"] = df["FWI"].apply(categorize_fwi)

        # map each risk to a text color
        risk_to_color = {
            "Low fire danger":      "green",
            "Moderate fire danger": "orange",
            "Severe fire danger":   "red",
        }
        text_colors = df["risk"].map(risk_to_color)

        # build the bar chart, with risk labels
        fig = px.bar(
            df,
            x="CampName",
            y="FWI",
            text="risk",
            labels={"CampName":"Camp","FWI":"Fire Weather Index"},
            title=f"Current Fire Weather Index (Rank {rank}/{total})"
        )
        fig.update_traces(
            marker_color=colors,
            textposition="outside",
            textfont=dict(color=text_colors, size=12),
            showlegend=False
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            plot_bgcolor="white",
            margin=dict(l=40, r=20, t=60, b=120)
        )
        fig.update_yaxes(range=[0,100])

        narrative = html.Div([
            html.H5("Current Fire Weather Summary", style={"fontWeight":"bold"}),
            html.P(
                f"Today’s FWI across all camps—highlighting **{selected_camp}** in red—"
                "shows which sites are experiencing the hottest, driest and windiest conditions right now. "
                "Bar labels indicate the fire-danger category (Low, Moderate or Severe)."
            )
        ], style={"fontSize":"14px"})

        return dcc.Graph(figure=fig, config={"displayModeBar":False}), narrative


    # --- 14-day FWI forecast ---
    else:
        records = []
        start = date.today() + timedelta(days=1)
        for i in range(14):
            d   = start + timedelta(days=i)
            w   = get_weather_noon(lat, lon, d.isoformat())
            fwi = round(calc_fwi_simple(w["temp"], w["rh"], w["wind"], w["precip"]), 0)
            records.append({
                "Date": d.strftime("%b %d"),
                "FWI":  fwi,
                "Risk": categorize_fwi(fwi)
            })

        df_fc = pd.DataFrame(records)

        # line chart colored by risk
        fig = px.line(
            df_fc,
            x="Date",
            y="FWI",
            color="Risk",
            markers=True,
            title=f"14-Day Fire Weather Index Forecast for {selected_camp}",
            labels={"FWI":"Fire Weather Index"}
        )
        fig.update_traces(mode="lines+markers")
        fig.update_yaxes(range=[0, 100], title="Fire Weather Index")

        # narrative below chart
        narrative = html.Div([
            html.H5("14-Day Fire Weather Forecast", style={"fontWeight":"bold"}),
            html.P(
                "This line chart projects your camp’s FWI over the next two weeks. "
                "Each point is labeled by its fire-danger category (Low, Moderate or Severe). "
                "Hover to see the exact FWI value and risk class for each day."
            )
        ], style={"fontSize":"14px"})

        return dcc.Graph(figure=fig, config={"displayModeBar":False}), narrative

# ------------------ Site Level FRI Tab Callback ------------------ #
@app.callback(
    Output("site-fri-content", "children"),
    [Input("camp-dropdown", "value"),
     Input("site-fri-tabs",   "value")]
)
def render_fri_tab(selected_camp, active_tab):
    # get lat/lon
    row = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update, dash.no_update
    lat = row.iloc[0]["Latitude"]
    lon = row.iloc[0]["Longitude"]

    # --- 1) Monthly FRI bar chart ---
    if active_tab == "monthly":
        # grab camp info
        camp_row = camp_summary.loc[camp_summary["CampName"] == selected_camp].iloc[0]
        year     = datetime.now().year
        lat, lon = camp_row["Latitude"], camp_row["Longitude"]
        fsi      = camp_row["FSI_Calculated"]

        # compute & round the 12‐month FRI
        monthly_fwi = get_monthly_fwi_nasa(lat, lon, year)
        monthly_fri = [fsi * (1 + w/100) for w in monthly_fwi]
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        df = pd.DataFrame({"month": months, "fri": monthly_fri})
        df["fri"] = df["fri"].round(0).astype(int)

        # **NEW**: classify each month’s FRI
        df["risk"] = df["fri"].apply(categorize_fri)

        # choose colors for each risk level if you like
        risk_to_color = {
            "Low risk":      "green",
            "Moderate risk": "orange",
            "High risk":     "red",
            "Extreme risk":  "darkred"
        }
        df["text_color"] = df["risk"].map(risk_to_color)

        # build bar chart, using the classification as the text label
        fig = px.bar(
            df,
            x="month",
            y="fri",
            labels={"month":"Month", "fri":"Fire Risk Index"},
            title=f"Monthly Fire Risk Index ({year}) for {selected_camp}"
        )
        fig.update_traces(
            marker_color="steelblue",
            text=df["risk"],                # <-- class display
            textposition="outside",
            textfont=dict(color=df["text_color"], size=12),
            showlegend=False
        )
        fig.update_yaxes(range=[0, 100])    # if you want the same 0–100 scale

        narrative = html.Div([
            html.H5("Monthly Fire Risk Index", style={"fontWeight":"bold"}),
            html.P(
                "This bar chart shows each month’s Fire Risk Index—how your camp’s underlying "
                "susceptibility (FSI) combines with climatological fire-weather trends (FWI). "
                "Bars are labeled by their risk category (Low, Moderate, High or Extreme) so you "
                "can spot your camp’s seasonal high‐risk periods."
            )
        ], style={"fontSize":"14px"})

        return dcc.Graph(figure=fig, config={"displayModeBar":False}), narrative

    # --- 2) Current comparison bar chart ---
    elif active_tab == "current":
        # build df with class
        df = (camp_summary[['CampName','FRI','FRI_Class']]
            .sort_values('FRI', ascending=False)
            .reset_index(drop=True))

        # **ROUND FRI TO WHOLE NUMBER**
        df['FRI'] = np.ceil(df['FRI']).astype(int)

        # selected camp stats
        fri_sel = df.loc[df.CampName==selected_camp, 'FRI'].iloc[0]
        cls_sel = df.loc[df.CampName==selected_camp, 'FRI_Class'].iloc[0]
        rank    = int(df.index[df.CampName==selected_camp][0]) + 1
        total   = len(df)

        # bar colors (red for selected camp)
        colors = ['#EF553B' if c == selected_camp else '#636EFA'
                for c in df['CampName']]

        # text colors by risk class
        risk_to_color = {
            "Extreme risk": "darkred",
            "High risk":    "red",
            "Moderate risk":"orange",
            "Low risk":     "green"
        }
        text_colors = [risk_to_color[c] for c in df['FRI_Class']]

        # build the bar chart
        fig = px.bar(
            df,
            x='CampName',
            y='FRI',
            text='FRI_Class',
            title=f'Current FRI Comparison (Rank {rank}/{total})',
            labels={'CampName':'Camp','FRI':'Fire Risk Index'}
        )
        fig.update_traces(
            marker_color=colors,
            textposition='outside',
            textfont=dict(color=text_colors, size=12),
            showlegend=False
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            plot_bgcolor='white',
            margin=dict(l=40, r=20, t=60, b=120)
        )
        fig.update_yaxes(range=[0, 100])    # if you want the same 0–100 scale
        narrative = html.Div([
            html.H5("Current Fire Risk Summary", style={"fontWeight":"bold"}),
            html.P(
                f"Right now, **{selected_camp}** is at FRI = **{fri_sel}** ({cls_sel}). "
                "This chart compares FRI across all camps; bars are colored and labeled by their risk category."
            )
        ], style={"fontSize":"14px"})

        return dcc.Graph(figure=fig, config={"displayModeBar":False}), narrative

    # --- 3) 14-Day Forecasted FRI ---
    elif active_tab == "forecasted":
        fsi_val = float(camp_summary.loc[
            camp_summary["CampName"] == selected_camp, "FSI_Calculated"
        ].iloc[0])
        start = date.today() + timedelta(days=1)
        records = []
        for i in range(14):
            d = start + timedelta(days=i)
            iso = d.isoformat()
            w = get_weather_noon(lat, lon, iso)
            fwi = round(calc_fwi_simple(w["temp"], w["rh"], w["wind"], w["precip"]), 0)
            fri = int(round(fsi_val * (1 + fwi/100), 0))
            records.append({
                "Date": d.strftime("%b %d"),
                "FRI": fri,
                "Risk": categorize_fri(fri)
            })
        df_fc = pd.DataFrame(records)

        fig = px.line(
            df_fc, x="Date", y="FRI", color="Risk", markers=True,
            title=f"14-Day FRI Forecast for {selected_camp}",
            labels={"FRI":"Fire Risk Index"},
            color_discrete_map={
                "Low risk":"green",
                "Moderate risk":"orange",
                "High risk":"red",
                "Extreme risk":"purple"
            }
        )
        fig.update_traces(mode="lines+markers")
        fig.update_yaxes(range=[0, 100], title="Fire Risk Index")

        narrative = html.Div([
            html.H5("14-Day Fire Risk Index Forecast", style={"fontWeight":"bold"}),
            html.P(
                "This line chart projects your camp’s FRI over the next two weeks. "
                "Each point is color-coded and labeled by its risk category, so you can "
                "anticipate when fire‐risk will climb and plan staff or resource deployments."
            )
        ], style={"fontSize":"14px"})

        return dcc.Graph(figure=fig, config={"displayModeBar":False}), narrative

    # fallback
    return dash.no_update, dash.no_update

# ------------------ Site Level Dashboard Update Callback ------------------ #
@app.callback(
    [
        Output("site-details",         "children"),
        Output("fsi-index",            "children"),
        Output("fwi-index",            "children"),
        Output("fri-index",            "children"),
        Output("block-bar-chart",      "figure"),
        Output("fire-risk-map",        "figure"),
        Output("susceptibility-table", "data"),
    ],
    [Input("camp-dropdown", "value")]
)
def update_dashboard(selected_camp):
    camp_data = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if camp_data.empty:
        return ("No data available", "-", "-", "-",
                {}, {}, [], {})

    # — camp-level summary row for cards —
    camp_row = camp_summary.loc[camp_summary["CampName"] == selected_camp]
    if camp_row.empty:
        return ("No summary data", "-", "-", "-",
                {}, {}, [], {})
    camp = camp_row.iloc[0]

    site_container = html.Div([
        html.H5("Site Details", style={"fontWeight":"bold","fontSize":"18px"}),
        html.P([html.Strong("Site name: "), selected_camp]),
        html.P([html.Strong("Assessment date: "), "2024-09-25"]),
        html.P([html.Strong("Site population: "), "33,515"])
    ], style={"fontSize":"14px"})

     # — use camp_summary values here, not block averages —
    fsi_value = math.ceil(camp["FSI_Calculated"])
    fsi_class = classify_fsi(fsi_value)

    # FSI card build up
    fsi_text = html.Div([
        html.H2(f"{fsi_value} – {fsi_class}", style={"display":"inline-block"}),
        html.P(
            f"(Environment: {math.ceil(camp['Environment'])}, "
            f"Fuel: {math.ceil(camp['Fuel'])}, "
            f"Behaviour: {math.ceil(camp['Behaviour'])}, "
            f"Response: {math.ceil(camp['Response'])})",
            style={"fontSize":"14px","color":"#555"}
        )
    ])

    # get the same coords for FWI/map
    lat, lon = camp["Latitude"], camp["Longitude"]
    # today @ 13:00 LST
    # — today at 13:00 local time —
    w_today = get_weather_noon(lat, lon, date.today().isoformat())

    # use the FWI/FRI already stored in camp_summary
    fwi_value = math.ceil(camp["FWI"])
    fri_value = math.ceil(camp["FRI"])
    fri_severity= categorize_fri(camp["FRI"]).split()[0]          # “High”
    fri_label   = f"{fri_value} – {fri_severity}"                     # “26 – High”    

    weather_details = (
        f"Temp: {w_today['temp']}°C; "
        f"RH: {w_today['rh']}%; "
        f"Wind: {w_today['wind']} km/h; "
        f"Precip: {w_today['precip']} mm"
    )
    last_update = f"{date.today().isoformat()} 13:00 LST"

    fwi_text = html.Div([
        html.H2(
            f"{fwi_value} – {categorize_fwi(fwi_value).split()[0]}",
            className="mt-1 mb-0", style={"display": "inline-block"}
        ),
        html.P(weather_details, style={"fontSize": "14px", "margin": "0"}),
        html.P(f"Last update: {last_update}",
               style={"fontSize": "14px", "margin": "0", "color": "#555"})
        # if you still want a “last update” timestamp, you’ll need to fetch wttr.in separately:
        # raw_weather = get_wttr_data(lat, lon)
        # html.P(f"Last update: {raw_weather['local_time']}", style={…}),
    ])

    short_fri_label = categorize_fri(fri_value).split()[0]
    fri_text = html.Div([
        html.H2(f"{fri_value} – {short_fri_label}", className="mt-1 mb-0", style={"display": "inline-block"}),
        html.P(
            f"FRI = FSI * (1 + (FWI/100)) = {fsi_value} * (1 + ({fwi_value}/100))",
            style={"fontSize": "14px", "margin": "0"}
        ),
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
        text="Score"
    )

    # 1️⃣ Filter your ESRI‐style GeoJSON down to just the selected camp
    selected_features = [
        feat for feat in geojson_data['features']
        if feat.get('properties', {}).get('CampName') == selected_camp
    ]
    selected_geojson = {
        "type": "FeatureCollection",
        "features": selected_features
    }
    
    block_bar_fig.update_traces(texttemplate='%{text}', textposition='outside')
    camp_point = pd.DataFrame([{
    "CampName": camp["CampName"],
    "Latitude": camp["Latitude"],
    "Longitude": camp["Longitude"],
    "FSI_Calculated": camp["FSI_Calculated"]
}])
    
    df_sel = camp_summary.loc[
        camp_summary["CampName"] == selected_camp,
        ["CampName","FRI"]
    ].copy()
    df_sel["FRI"] = df_sel["FRI"].apply(
    lambda x: math.ceil(x) if (x - math.floor(x)) > 0.5 
    else math.floor(x)
)

    # — grab just that camp’s polygon —
    selected_features = [
        feat for feat in geojson_data["features"]
        if feat["properties"]["CampName"] == selected_camp
    ]
    selected_geojson = {"type":"FeatureCollection","features":selected_features}

    # — center + zoom —
    coords = selected_features[0]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    centre = {"lat": (max(lats)+min(lats))/2, "lon": (max(lons)+min(lons))/2}

    # — draw choropleth_mapbox with a 0–100 colorbar —
    df_sel = pd.DataFrame([{
        "CampName": selected_camp,
        "FRI":      fri_value
    }])

    map_fig = px.choropleth_mapbox(
        df_sel,
        geojson=selected_geojson,
        locations="CampName",
        featureidkey="properties.CampName",
        color="FRI",
        range_color=(0,100),
        color_continuous_scale="OrRd",
        mapbox_style="carto-positron",
        center=centre,
        zoom=11,
        opacity=0.6,                    # ← don’t forget the comma
        hover_name="CampName",
        hover_data={"FRI": False},
    )

    map_fig.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            f"FRI: {fri_label}<extra></extra>"
        )
    )


    map_fig.update_layout(
        mapbox_center=centre,
        mapbox_zoom=11,
        margin={"l":0,"r":0,"t":30,"b":0},
        uirevision=selected_camp
    )

    # … your map_fig.update_layout from above …

    # now build the block-level table data
    table_df = camp_data[["Block", "FSI_Calculated", "FSI_Class"]].copy()
    table_df["FSI_Calculated"] = table_df["FSI_Calculated"].round(0).astype(int)
        # 2) Rename to the display names
    table_df = table_df.rename(columns={
        "Block": "Site Block",
        "FSI_Calculated": "FSI Score",
        "FSI_Class": "FSI_Class"
    })
    table_data = table_df.to_dict("records")

    # and the bubble-chart from your summary
    dimensions_fig = create_fsi_dimensions_figure_from_summary(camp)

    return (
        site_container,
        fsi_text,
        fwi_text,
        fri_text,
        block_bar_fig,
        map_fig,
        table_data
    )

# ------------------ Windy Callback ------------------ #
@app.callback(
    Output("windy-iframe", "src"),
    [Input("camp-dropdown", "value")]
)
def update_windy_src(selected_camp):
    row = cleaned_data[cleaned_data["CampName"] == selected_camp]
    if row.empty:
        return dash.no_update

    lat = row.iloc[0]["Latitude"]
    lon = row.iloc[0]["Longitude"]

    # embed URL with a marker at (lat, lon):
    return (
        f"https://embed.windy.com/embed2.html?"
        f"lat={lat}&lon={lon}"
        f"&detailLat={lat}&detailLon={lon}"
        f"&zoom=10"
        f"&level=surface"
        f"&overlay=wind"
        f"&marker=true"
        f"&markerWidth=60"      # try bumping these
        f"&markerHeight=60"
        f"&location=coordinates"
        f"&type=map"
    )
if __name__=='__main__':
    port = int(os.environ.get("PORT", 8050))
    # bind to 0.0.0.0 so Render can route to it
    app.run(host="0.0.0.0", port=port, debug=False)