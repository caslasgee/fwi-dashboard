# layouts.py
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from fire_risk.legacy.data import cleaned_data

FA_URL = "https://use.fontawesome.com/releases/v5.15.4/css/all.css"


def section_card(title, body, body_bg=None, icon=None, **card_kwargs):
    header_children = []
    if icon:
        header_children.append(
            html.I(className=f"{icon} me-2", style={"fontSize": "18px"})
        )
    header_children.append(title)

    header = dbc.CardHeader(
        html.Div(header_children, className="d-flex align-items-center"),
        className="fw-semibold small",
        style={"backgroundColor": "white"},
    )

    if body_bg is not None:
        body = dbc.CardBody(
            body,
            style={"backgroundColor": body_bg, "borderRadius": "0 0 10px 10px"},
        )
    else:
        body = dbc.CardBody(body)

    return dbc.Card(
        [header, body],
        className="shadow-sm mb-3",
        style={"borderRadius": "10px"},
        **card_kwargs,
    )


navbar = dbc.Navbar(
    dbc.Container(
        fluid=True,
        children=[
            dbc.Row(
                [
                    dbc.Col(
                        dbc.NavbarBrand(
                            [
                                html.Img(
                                    src="https://upload.wikimedia.org/wikipedia/commons/9/99/FireIcon.svg",
                                    style={
                                        "height": "30px",
                                        "marginRight": "10px",
                                    },
                                ),
                                "Fire Risk Analysis",
                            ],
                            className="text-white",
                            style={"fontSize": "28px", "fontWeight": "bold"},
                        ),
                        width="auto",
                        style={"paddingLeft": 0},
                    ),
                    dbc.Col(
                        dbc.Nav(
                            [
                                dbc.NavItem(
                                    dbc.NavLink(
                                        "Site Level",
                                        href="/",
                                        active="exact",
                                    )
                                ),
                                dbc.NavItem(
                                    dbc.NavLink(
                                        "Block Level",
                                        href="/block",
                                        active="exact",
                                    )
                                ),
                                dbc.NavItem(
                                    dbc.NavLink(
                                        "Overview",
                                        href="/overview",
                                        active="exact",
                                    )
                                ),
                                dbc.NavItem(
                                    dbc.NavLink(
                                        "About",
                                        href="/about",
                                        active="exact",
                                    )
                                ),
                            ],
                            navbar=True,
                        ),
                        width="auto",
                        style={"marginLeft": "2rem"},
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.Div(
                                    id="camp-dropdown-container",
                                    children=[
                                        html.Span(
                                            "Select a camp:",
                                            style={
                                                "color": "white",
                                                "marginRight": "8px",
                                            },
                                        ),
                                        dcc.Dropdown(
                                            id="camp-dropdown",
                                            options=[
                                                {
                                                    "label": c,
                                                    "value": c,
                                                }
                                                for c in sorted(
                                                    cleaned_data[
                                                        "CampName"
                                                    ].unique()
                                                )
                                            ],
                                            value=(
                                                sorted(
                                                    cleaned_data[
                                                        "CampName"
                                                    ].unique()
                                                )[0]
                                                if not cleaned_data.empty
                                                else None
                                            ),
                                            clearable=False,
                                            style={
                                                "width": "200px",
                                                "fontSize": "14px",
                                            },
                                        ),
                                    ],
                                    style={
                                        "display": "flex",
                                        "alignItems": "center",
                                        "justifyContent": "flex-end",
                                    },
                                ),
                                html.Div(
                                    id="block-filter-container",
                                    children=[
                                        html.Span(
                                            "Camp / Block:",
                                            style={
                                                "color": "white",
                                                "marginRight": "8px",
                                            },
                                        ),
                                        dcc.Dropdown(
                                            id="block-camp-dropdown",
                                            options=[
                                                {
                                                    "label": c,
                                                    "value": c,
                                                }
                                                for c in sorted(
                                                    cleaned_data[
                                                        "CampName"
                                                    ]
                                                    .dropna()
                                                    .unique()
                                                )
                                            ],
                                            value=None,
                                            placeholder="Select camp",
                                            clearable=True,
                                            style={
                                                "width": "190px",
                                                "fontSize": "14px",
                                                "marginRight": "6px",
                                            },
                                        ),
                                        dcc.Dropdown(
                                            id="block-block-dropdown",
                                            options=[],
                                            value=None,
                                            placeholder="Select block",
                                            clearable=True,
                                            style={
                                                "width": "190px",
                                                "fontSize": "14px",
                                            },
                                        ),
                                    ],
                                    style={
                                        "display": "none",
                                        "alignItems": "center",
                                        "justifyContent": "flex-end",
                                    },
                                ),
                            ],
                            style={
                                "display": "flex",
                                "alignItems": "center",
                                "gap": "12px",
                            },
                        ),
                        width="auto",
                        style={"marginLeft": "auto"},
                    ),
                ],
                align="center",
                className="w-100",
            )
        ],
    ),
    color="#0033A0",
    dark=True,
)


def site_level_layout():
    return dbc.Container(
        [
            html.Br(),
            dbc.Row(
                [
                    dbc.Col(
                        section_card(
                            "Site Details",
                            html.Div(
                                id="site-details",
                                style={
                                    "fontSize": "14px",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "gap": "2px",
                                },
                            ),
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        section_card(
                            "Site Susceptibility Index",
                            html.Div(
                                [html.Div(id="fsi-index")],
                                className="text-center",
                            ),
                            body_bg="#E0B654",
                            icon="fas fa-map-marker-alt",
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        section_card(
                            "Fire Weather Index (current & yearly mean)",
                            html.Div(
                                [html.Div(id="fwi-index")],
                                className="text-center",
                            ),
                            body_bg="#C8FFD4",
                            icon="fas fa-thermometer-half",
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        section_card(
                            "Fire Risk Index (current & yearly mean)",
                            html.Div(
                                [html.Div(id="fri-index")],
                                className="text-center",
                            ),
                            body_bg="#B3B3B3",
                            icon="fas fa-exclamation-triangle",
                        ),
                        width=3,
                    ),
                ],
                className="g-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        section_card(
                            "Camp Contact Information",
                            html.Div(
                                [
                                    html.A(
                                        "Show / hide contact details",
                                        id="contact-toggle",
                                        style={
                                            "cursor": "pointer",
                                            "textDecoration": "underline",
                                            "color": "#007bff",
                                        },
                                    ),
                                    dbc.Collapse(
                                        html.Div(
                                            id="contact-content",
                                            className="mt-3",
                                        ),
                                        id="contact-collapse",
                                        is_open=False,
                                        style={
                                            "backgroundColor": "#f8f9fa",
                                            "borderRadius": "5px",
                                            "padding": "8px",
                                        },
                                    ),
                                ]
                            ),
                        ),
                        width=12,
                    )
                ]
            ),
            dbc.Row(
                [
                dbc.Col(
                    section_card(
                        "Fire Risk Index",
                        html.Div(
                            [
                                dcc.Tabs(
                                    id="site-fri-tabs",
                                    value="current",
                                    children=[
                                        dcc.Tab(label="Current", value="current"),
                                        dcc.Tab(label="Monthly", value="monthly"),
                                        dcc.Tab(label="Forecast", value="forecasted"),
                                    ],
                                ),
                                html.Div(
                                    id="site-fri-content",
                                    className="mt-3",
                                ),
                                html.Div(
                                    id="site-fri-narrative",
                                    className="mt-3",
                                ),
                            ]
                        ),
                    ),
                    width=6,
                ),
                    dbc.Col(
                        section_card(
                            "Fire Weather Index",
                            html.Div(
                                [
                                    dcc.Tabs(
                                        id="site-fwi-tabs",
                                        value="current",
                                        children=[
                                            dcc.Tab(
                                                label="Current",
                                                value="current",
                                            ),
                                            dcc.Tab(
                                                label="Monthly",
                                                value="monthly",
                                            ),
                                            dcc.Tab(
                                                label="Forecast",
                                                value="forecasted",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        id="site-fwi-content",
                                        className="mt-3",
                                    ),
                                    html.Div(
                                        id="site-fwi-narrative",
                                        className="mt-3",
                                    ),
                                ]
                            ),
                        ),
                        width=6,
                    ),
                ],
                className="g-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        section_card(
                            "Camp Boundary FRI Heatmap",
                            dcc.Graph(
                                id="fire-risk-map",
                                config={"displayModeBar": False},
                            ),
                        ),
                        width=6,
                    ),
                    dbc.Col(
                        section_card(
                            "Live Wind Map",
                            html.Iframe(
                                id="windy-iframe",
                                style={
                                    "width": "100%",
                                    "height": "400px",
                                    "border": "none",
                                },
                            ),
                        ),
                        width=6,
                    ),
                ],
                className="g-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        section_card(
                            "Block-Level Susceptibility Scores",
                            dcc.Graph(
                                id="block-bar-chart",
                                config={"displayModeBar": False},
                            ),
                        ),
                        width=6,
                    ),
                    dbc.Col(
                        section_card(
                            "Fire Susceptibility Indicator Scores",
                            dash_table.DataTable(
                                id="susceptibility-table",
                                columns=[
                                    {
                                        "name": "Site Block",
                                        "id": "Site Block",
                                    },
                                    {
                                        "name": "FSI Score",
                                        "id": "FSI Score",
                                    },
                                    {
                                        "name": "FSI Class",
                                        "id": "FSI_Class",
                                    },
                                ],
                                data=[],
                                style_table={"overflowX": "auto"},
                                style_cell={
                                    "fontSize": "14px",
                                    "textAlign": "left",
                                },
                            ),
                        ),
                        width=6,
                    ),
                ],
                className="g-3",
            ),
            page_footer(),
        ],
        fluid=True,
    )


def block_level_layout():
    return dbc.Container(
        [
            html.Br(),
            html.Div(id="block-page-body"),
        ],
        fluid=True,
    )


def overview_layout():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.H2("Overview", className="mb-1"),
                                html.P(
                                    "Mission-wide fire risk overview across camps, with ranking, severity distribution, and map-based risk patterns.",
                                    className="text-muted mb-0",
                                ),
                            ]
                        ),
                        width=8,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.Label("Filter by Severity", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id="overview-severity-filter",
                                    options=[
                                        {"label": "All", "value": "All"},
                                        {"label": "Extreme risk", "value": "Extreme risk"},
                                        {"label": "High risk", "value": "High risk"},
                                        {"label": "Moderate risk", "value": "Moderate risk"},
                                        {"label": "Low risk", "value": "Low risk"},
                                    ],
                                    value="All",
                                    clearable=False,
                                ),
                            ]
                        ),
                        width=4,
                    ),
                ],
                className="mb-3",
            ),

            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Camps in View", className="text-muted"),
                                    html.H3(id="overview-kpi-total-camps", className="mb-0"),
                                ]
                            )
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Extreme Risk Camps", className="text-muted"),
                                    html.H3(id="overview-kpi-extreme", className="mb-0 text-danger"),
                                ]
                            )
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("High Risk Camps", className="text-muted"),
                                    html.H3(id="overview-kpi-high", className="mb-0", style={"color": "#d97706"}),
                                ]
                            )
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Average FRI", className="text-muted"),
                                    html.H3(id="overview-kpi-avg-fri", className="mb-0"),
                                ]
                            )
                        ),
                        width=3,
                    ),
                ],
                className="g-3 mb-3",
            ),

            dbc.Row(
    [
        dbc.Col(
            html.Div(
                [
                    html.H5("Understanding the Fire Risk Overview", style={"fontWeight": "bold"}),

            html.P(
                "This dashboard combines structural fire susceptibility and real-time fire-weather "
                "conditions to estimate the relative likelihood of fire spread across the camps. "
                "The Fire Risk Index (FRI) integrates two components: the Fire Susceptibility Index "
                "(FSI), which reflects structural and behavioural vulnerability within camps, and "
                "the Fire Weather Index (FWI), which captures the influence of temperature, humidity, "
                "wind, and rainfall on fire behaviour."
            ),

            html.P(
                "Current fire weather conditions are derived from near-real-time meteorological data "
                "and processed using the Canadian Fire Weather Index System (CFFWIS) implemented "
                "through the xclim scientific library. These weather conditions influence how quickly "
                "a fire could ignite, spread, and intensify if an ignition occurs."
            ),

            html.P(
                "For short-term outlooks, the dashboard generates a 14-day projection of fire weather "
                "conditions using forecast meteorological data. The forecast Fire Weather Index "
                "is computed sequentially so that fuel moisture conditions evolve day-by-day, "
                "mirroring how fire potential builds or declines in reality."
            ),

            html.P(
                "Projected Fire Risk Index values also incorporate a short-term adjustment to fire "
                "susceptibility based on forecast weather patterns. Extended dry periods, strong winds, "
                "and low humidity increase short-term vulnerability, while rainfall reduces it."
            ),

            html.P(
                "The overview page helps identify which camps currently face the highest relative "
                "fire risk, allowing operational teams to prioritise prevention activities, "
                "preparedness measures, and rapid response capacity."
            ),

            html.P(
                "While these indicators provide a useful operational screening tool, they should "
                "be interpreted as risk signals rather than predictions of fire occurrence. "
                "Actual incidents depend on ignition sources, human behaviour, and local conditions."
            ),
        ],
                style={
                    "backgroundColor": "#f8f9fa",
                    "padding": "15px",
                    "borderRadius": "8px",
                    "marginTop": "20px",
                },
            ),
            width=12,
        )
    ]
),

            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Camp Fire Risk Map", className="mb-3"),
                                    dcc.Graph(id="overview-heatmap", config={"displayModeBar": False}),
                                ]
                            )
                        ),
                        width=8,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Severity Distribution", className="mb-3"),
                                    dcc.Graph(id="overview-severity-donut", config={"displayModeBar": False}),
                                    html.Hr(),
                                    html.H5("Top 5 Highest-Risk Camps", className="mb-3"),
                                    html.Div(id="overview-top5"),
                                ]
                            )
                        ),
                        width=4,
                    ),
                ],
                className="g-3 mb-3",
            ),

            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Camp Risk Ranking", className="mb-3"),
                                    dash_table.DataTable(
                                        id="overview-table",
                                        columns=[
                                            {"name": "Rank", "id": "Rank"},
                                            {"name": "Camp", "id": "Camp"},
                                            {"name": "FSI", "id": "FSI"},
                                            {"name": "FWI", "id": "FWI"},
                                            {"name": "FRI", "id": "FRI"},
                                            {"name": "Severity", "id": "FRI Severity"},
                                        ],
                                        page_size=10,
                                        style_table={"overflowX": "auto"},
                                        style_cell={
                                            "textAlign": "center",
                                            "padding": "8px",
                                            "fontSize": "13px",
                                        },
                                        style_header={
                                            "fontWeight": "bold",
                                            "backgroundColor": "#f2f2f2",
                                        },
                                        style_data_conditional=[
                                            {
                                                "if": {
                                                    "filter_query": '{FRI Severity} = "Extreme risk"',
                                                    "column_id": "FRI Severity",
                                                },
                                                "backgroundColor": "#b91c1c",
                                                "color": "white",
                                            },
                                            {
                                                "if": {
                                                    "filter_query": '{FRI Severity} = "High risk"',
                                                    "column_id": "FRI Severity",
                                                },
                                                "backgroundColor": "#ea580c",
                                                "color": "white",
                                            },
                                            {
                                                "if": {
                                                    "filter_query": '{FRI Severity} = "Moderate risk"',
                                                    "column_id": "FRI Severity",
                                                },
                                                "backgroundColor": "#facc15",
                                                "color": "black",
                                            },
                                            {
                                                "if": {
                                                    "filter_query": '{FRI Severity} = "Low risk"',
                                                    "column_id": "FRI Severity",
                                                },
                                                "backgroundColor": "#86efac",
                                                "color": "black",
                                            },
                                        ],
                                    ),
                                ]
                            )
                        ),
                        width=8,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Operational Summary", className="mb-3"),
                                    html.Div(id="overview-narrative"),
                                ]
                            )
                        ),
                        width=4,
                    ),

                ],
                className="g-3",
            ),
            page_footer(),
        ],
        fluid=True,
        className="mt-3",
    )

def page_footer():
    return html.Footer(
        dbc.Container(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            html.Div(
                                [
                                    html.Img(
                                        src="/assets/iom_logo_white.png",
                                        style={"height": "30px", "marginRight": "10px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                "All rights reserved - IOM",
                                                style={
                                                    "color": "white",
                                                    "fontWeight": "700",
                                                    "fontSize": "14px",
                                                    "lineHeight": "1.2",
                                                },
                                            ),
                                            html.Div(
                                                "Fire Risk Dashboard",
                                                style={
                                                    "color": "rgba(255,255,255,0.85)",
                                                    "fontSize": "12px",
                                                    "lineHeight": "1.2",
                                                },
                                            ),
                                        ]
                                    ),
                                ],
                                className="d-flex align-items-center",
                            ),
                            xs=12, md=4,
                            className="mb-3 mb-md-0",
                        ),
                        dbc.Col(
                            html.Div(
                                [
                                    html.Span(
                                        "Methodology & data sources:",
                                        style={
                                            "color": "white",
                                            "fontWeight": "600",
                                            "marginRight": "10px",
                                            "fontSize": "13px",
                                        },
                                    ),
                                    html.A(
                                        "xclim",
                                        href="https://xclim.readthedocs.io/en/stable/indices.html",
                                        target="_blank",
                                        style={"color": "white", "textDecoration": "underline", "marginRight": "10px", "fontSize": "13px"},
                                    ),
                                    html.A(
                                        "CFFWIS",
                                        href="https://cwfis.cfs.nrcan.gc.ca/background/summary/fwi",
                                        target="_blank",
                                        style={"color": "white", "textDecoration": "underline", "marginRight": "10px", "fontSize": "13px"},
                                    ),
                                    html.A(
                                        "Open-Meteo",
                                        href="https://open-meteo.com/en/docs",
                                        target="_blank",
                                        style={"color": "white", "textDecoration": "underline", "marginRight": "10px", "fontSize": "13px"},
                                    ),
                                    html.A(
                                        "NASA POWER",
                                        href="https://power.larc.nasa.gov/docs/services/api/",
                                        target="_blank",
                                        style={"color": "white", "textDecoration": "underline", "fontSize": "13px"},
                                    ),
                                ],
                                className="d-flex flex-wrap justify-content-md-end align-items-center",
                            ),
                            xs=12, md=8,
                        ),
                    ],
                    className="align-items-center",
                )
            ],
            fluid=True,
        ),
        style={
            "backgroundColor": "#0033A0",
            "padding": "16px 24px",
            "marginTop": "24px",
        },
    )

def about_layout():
    return dbc.Container(
        [
            html.H2("How This Dashboard Works", className="mt-3"),
            html.H4("Data Sources & Update Frequency"),
            html.Ul(
                [
                    html.Li("Camp survey data (FSI): updated regularly."),
                    html.Li(
                        "On-the-day fire weather (FWI): fetched daily at 13:00 local time via Open-Meteo API."
                    ),
                    html.Li(
                        "Monthly fire weather climatology: NASA POWER monthly aggregates (with 1991–2020 fallback)."
                    ),
                ]
            ),
            html.H4("Calculation Methods"),
            html.P(
                "Fire Weather Index (FWI) is computed using the Canadian Forest Fire Weather Index System "
                "implementation from the xclim library (CFFWIS), driven by temperature, relative humidity, "
                "wind speed and precipitation from either Open-Meteo (daily) or NASA POWER (monthly). "
                "Fire Risk Index (FRI) scales the structural fire susceptibility (FSI) of each site by the "
                "prevailing or projected fire weather (FWI).",
                style={
                    "backgroundColor": "#f8f9fa",
                    "padding": "10px",
                    "borderRadius": "5px",
                },
            ),
            html.P(
                "FWI methodology adapted from the Canadian Forest Fire Weather Index System (Van Wagner, 1987).",
                style={
                    "fontSize": "13px",
                    "color": "#666",
                    "fontStyle": "italic",
                    "marginTop": "8px",
                },
            ),
            html.H4("Team & Support"),
            html.P("Maintained by the XXX Team"),
            html.P("Contact: xxxxxxxxxxxx"),
            html.H4("Version History"),
            html.Ul(
                [
                    html.Li(
                        "v1.0 – Initial release with FSI, simple FWI & FRI calculations."
                    ),
                    html.Li(
                        "v1.1 – Integrated xclim CFFWIS, monthly NASA POWER climatology, and 14-day forecast."
                    ),
                    html.Li(
                        "v1.2 – Added monthly narratives and map filtering, plus enhanced Overview metrics."
                    ),
                ]
            ),
            html.H4("Glossary"),
            html.Table(
                [
                    html.Tr([html.Th("Term"), html.Th("Definition")]),
                    html.Tr(
                        [html.Td("FSI"), html.Td("Fire Susceptibility Index")]
                    ),
                    html.Tr(
                        [
                            html.Td("FWI"),
                            html.Td("Fire Weather Index (xclim CFFWIS)"),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("FRI"),
                            html.Td("Fire Risk Index = FSI scaled by FWI"),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("Severity classes"),
                            html.Td(
                                "Low, Moderate, High, Extreme risk (for FRI); "
                                "Low, Moderate, Severe fire danger (for FWI)"
                            ),
                        ]
                    ),
                ],
                style={"width": "100%", "marginBottom": "2rem"},
            ),
            html.P(
                "Use the Overview tab for a high-level summary across all camps; "
                "the Site Level tab drills down to per-camp monthly, current, and forecasted fire risk."
            ),
            page_footer(),
        ],
    fluid=True,
)