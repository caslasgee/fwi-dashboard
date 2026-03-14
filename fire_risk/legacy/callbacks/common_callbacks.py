import pandas as pd
import dash_leaflet as dl
import dash_bootstrap_components as dbc
from dash import Input, Output, State, ctx, dash_table, html

from fire_risk.legacy.data import cleaned_data, block_geojson, equipment_df, geojson_data
from fire_risk.legacy.layouts import about_layout, block_level_layout, overview_layout, site_level_layout
from fire_risk.services.indicator_definitions import (
    DEFINITIONS_FILE,
    INDICATOR_DEFINITIONS_DF,
    INDICATOR_GROUPS,
)


def register_callbacks(app):
    # -------------------------------------------------------------------
    # EQUIPMENT MAP TITLE
    # -------------------------------------------------------------------
    @app.callback(
        Output("equipment-map-modal-title", "children"),
        Input("block-camp-dropdown", "value"),
        Input("block-block-dropdown", "value"),
    )
    def update_equipment_map_title(selected_camp, selected_block):
        if not selected_camp and not selected_block:
            return "Access and Infrastructure Map"

        block_text = str(selected_block).strip() if selected_block else ""
        camp_text = str(selected_camp).strip() if selected_camp else ""

        if block_text and not block_text.lower().startswith("block"):
            block_text = f"Block {block_text}"

        if block_text and camp_text:
            return f"Access and Infrastructure Map for {block_text}, Camp {camp_text}"
        if block_text:
            return f"Access and Infrastructure Map for {block_text}"
        if camp_text:
            return f"Access and Infrastructure Map for Camp {camp_text}"

        return "Access and Infrastructure Map"

    # -------------------------------------------------------------------
    # EQUIPMENT MAP HELPERS
    # -------------------------------------------------------------------
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
                    html.H6(str(row.get("Type_of facility", "Equipment")), className="mb-1"),
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
                style={"minWidth": "260px"},
            ),
            maxWidth=350,
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
            cleaned_data.loc[cleaned_data["CampName"] == selected_camp, "Block"]
            .dropna()
            .astype(str)
            .unique()
        )

        block_options = [{"label": b, "value": b} for b in sorted(blocks)]
        return block_options, None

    # -------------------------------------------------------------------
    # EQUIPMENT MAP CONTENT + BOUNDARIES + AUTO-FIT
    # -------------------------------------------------------------------
    @app.callback(
        Output("equipment-marker-layer", "children"),
        Output("equipment-boundary-layer", "children"),
        Output("equipment-summary-cards", "children"),
        Output("equipment-map", "center"),
        Output("equipment-map", "zoom"),
        Input("block-camp-dropdown", "value"),
        Input("block-block-dropdown", "value"),
    )
    def update_equipment_map(selected_camp, selected_block):
        dff = equipment_df.copy()

        if selected_camp:
            dff = dff[dff["camp_key"] == str(selected_camp).strip().upper()]

        if selected_block:
            dff = dff[dff["block_key"] == str(selected_block).strip().upper()]

        markers = []
        boundary_layers = []
        lats = []
        lons = []

        if not dff.empty:
            for _, row in dff.iterrows():
                lat = row.get("_LATITUDE")
                lon = row.get("_LONGITUDE")

                if pd.isna(lat) or pd.isna(lon):
                    continue

                lat = float(lat)
                lon = float(lon)

                lats.append(lat)
                lons.append(lon)

                markers.append(
                    dl.CircleMarker(
                        center=[lat, lon],
                        radius=6,
                        color=get_equipment_color(row.get("status_group")),
                        fill=True,
                        fillOpacity=0.8,
                        children=[make_equipment_popup(row)],
                    )
                )

        if geojson_data is not None and selected_camp:
            camp_features = [
                feat
                for feat in geojson_data["features"]
                if str(feat.get("properties", {}).get("CampName", "")).strip().upper()
                == str(selected_camp).strip().upper()
            ]

            if camp_features:
                boundary_layers.append(
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
                boundary_layers.append(
                    dl.GeoJSON(
                        data={"type": "FeatureCollection", "features": block_features},
                        options={"style": {"color": "red", "weight": 3, "fillOpacity": 0.08}},
                    )
                )

        if dff.empty:
            summary = dbc.Alert("No equipment found for the selected camp/block.", color="warning")
            return [], boundary_layers, summary, [21.2, 92.15], 14

        total_count = len(dff)
        functional_count = int((dff["status_group"] == "Functional").sum())
        non_functional_count = int((dff["status_group"] == "Non-functional").sum())
        top_types = dff["Type_of facility"].value_counts().head(3).to_dict()
        top_types_text = " | ".join([f"{k}: {v}" for k, v in top_types.items()]) if top_types else "N/A"

        summary = dbc.Row(
            [
                dbc.Col(dbc.Card(dbc.CardBody([html.H6("Total Equipment"), html.H4(total_count)])), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([html.H6("Functional"), html.H4(functional_count)])), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([html.H6("Non-functional"), html.H4(non_functional_count)])), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([html.H6("Top Types"), html.P(top_types_text)])), md=3),
            ],
            className="g-2",
        )

        center = [float(dff["_LATITUDE"].mean()), float(dff["_LONGITUDE"].mean())]

        if selected_block:
            zoom = 17
        elif selected_camp:
            zoom = 15
        else:
            zoom = 14

        return markers, boundary_layers, summary, center, zoom

    # -------------------------------------------------------------------
    # EQUIPMENT MODAL TOGGLE
    # -------------------------------------------------------------------
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
            return site_level_layout()

    # -------------------------------------------------------------------
    # INDICATOR MODAL TOGGLE
    # -------------------------------------------------------------------
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

    # -------------------------------------------------------------------
    # INDICATOR DEFINITIONS CONTENT
    # -------------------------------------------------------------------
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