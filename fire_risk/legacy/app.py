import dash
import dash_bootstrap_components as dbc
import dash_leaflet as dl
from dash import dcc, html, dash_table

from fire_risk.legacy.callbacks import (
    register_block_callbacks,
    register_common_callbacks,
    register_overview_callbacks,
    register_site_callbacks,
)
from fire_risk.legacy.layouts import (
    FA_URL,
    about_layout,
    block_level_layout,
    navbar,
    overview_layout,
    site_level_layout,
)

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP, FA_URL])
app.title = "Fire Risk Analysis - Site-Level"
app.config.suppress_callback_exceptions = True


def build_app_layout():
    return html.Div([
        dcc.Location(id="url", refresh=False),
        dcc.Interval(id="weather-refresh-interval", interval=15 * 60 * 1000, n_intervals=0),
        navbar,
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Indicator Definitions")),
            dbc.ModalBody(id="indicator-definition-content"),
            dbc.ModalFooter(dbc.Button("Close", id="close-indicator-modal", n_clicks=0)),
        ], id="indicator-modal", is_open=False, size="xl", scrollable=True),
        dbc.Offcanvas([html.H4("Action Plan", className="mb-3"), html.Div(id="action-plan-content")], id="action-plan-offcanvas", title="Action Plan", is_open=False, placement="start", scrollable=True, style={"width": "420px"}),
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle("Access and Infrastructure Map", id="equipment-map-modal-title")
            ),
            dbc.ModalBody([
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
            ]),
            dbc.ModalFooter(dbc.Button("Close", id="close-equipment-map", n_clicks=0)),
        ], id="equipment-map-modal", is_open=False, size="xl", scrollable=True),
        html.Hr(style={"margin": "0", "padding": "0", "borderTop": "1px solid #ccc"}),
        dcc.Tabs(id="fwi-tabs", value="seasonal", style={"display": "none"}),
        html.Div(id="page-content"),
    ])


app.layout = build_app_layout()
app.validation_layout = html.Div([
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
])

register_common_callbacks(app)
register_overview_callbacks(app)
register_block_callbacks(app)
register_site_callbacks(app)