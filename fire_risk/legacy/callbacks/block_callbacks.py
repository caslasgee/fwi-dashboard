import math
from datetime import date

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, dash_table
from fire_risk.legacy.layouts import section_card, page_footer

from fire_risk.legacy.layouts import section_card
from fire_risk.legacy.data import cleaned_data, response_details, block_geojson
from fire_risk.legacy.fwi_fri import (
    categorize_fri,
    categorize_fwi,
    classify_fsi,
    compute_fri,
    get_14day_fire_forecast,
    get_fwi_xclim,
    get_weather_noon,
)
from fire_risk.legacy.layouts import section_card
from fire_risk.services.indicator_definitions import build_indicator_score_table
from fire_risk.services.outlook_helpers import (
    build_fire_risk_outlook_calendar,
    build_monthly_outlook_df,
    build_monthly_outlook_heatmap,
    build_monthly_fri_narrative,
    build_monthly_fwi_narrative,
)
from fire_risk.services.risk_helpers import build_block_advisory_narrative
from fire_risk.services.common import OUTLOOK_YEAR, OUTLOOK_LABEL

MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def register_callbacks(app):
    def build_block_level_content(camp_name, block_name):
        block_data = cleaned_data[
            (cleaned_data["CampName"] == camp_name)
            & (cleaned_data["Block"] == block_name)
        ]

        if block_data.empty:
            return html.P("No data available for this block.", style={"color": "red"})

        camp_all = cleaned_data[cleaned_data["CampName"] == camp_name]

        assessment_text = "N/A"
        if "assessment_date" in block_data.columns:
            dates = pd.to_datetime(block_data["assessment_date"], errors="coerce").dropna()
            if not dates.empty:
                min_date = dates.min().date().isoformat()
                max_date = dates.max().date().isoformat()
                assessment_text = min_date if min_date == max_date else f"{min_date} to {max_date}"

        population_text = "N/A"
        pop_col = "ENV_003a"
        if pop_col in block_data.columns:
            site_pop = pd.to_numeric(block_data[pop_col], errors="coerce").fillna(0).sum()
            population_text = f"{site_pop:,.0f}"

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
                html.H2(f"{fsi_value} – {fsi_class}", className="mt-1 mb-2"),
                html.P(
                    [
                        html.Strong("FSI Severity: "),
                        fsi_class
                    ],
                    style={
                        "fontSize": "14px",
                        "margin": "0",
                        "textAlign": "center",
                        "color": "#555"
                    },
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

        last_update = f"{today_iso} (Noon weather conditions)"

        fwi_body = html.Div(
            [
                html.H2(
                    f"{fwi_value} – {categorize_fwi(fwi_value).split()[0]}",
                    className="mt-1 mb-1",
                ),
                html.P(
                    f"Weather reference: {today_iso} (noon conditions)",
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
                df_sel["is_selected"] = df_sel["BlockLabel"].str.strip().str.upper() == target
                df_sel["FRI_for_map"] = np.where(df_sel["is_selected"], df_sel["FRI"], 0)

                map_fig = px.choropleth_mapbox(
                    df_sel,
                    geojson=selected_geojson,
                    locations="BlockLabel",
                    featureidkey="properties.BlockLabel",
                    color="FRI_for_map",
                    range_color=(0, max(100, float(df_sel["FRI"].max()) + 5)),
                    color_continuous_scale=["#dddddd", "#fee8c8", "#fdbb84", "#e34a33"],
                    center=centre,
                    zoom=13,
                    opacity=0.85,
                    mapbox_style="carto-positron",
                    hover_name="BlockLabel",
                    hover_data={"FRI_for_map": False, "FRI": True},
                )

                map_fig.update_traces(marker_line_color="black", marker_line_width=1.5)

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

                map_children = dcc.Graph(figure=map_fig, config={"displayModeBar": False})

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
                dbc.Col(section_card("Selected Block Boundary (FRI)", map_children), width=6),
                dbc.Col(section_card("Live Wind Map (Block Focus)", windy_iframe), width=6),
            ],
            className="g-3 mb-3",
        )

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
        fig_dims.update_xaxes(range=[0, 100], tickvals=[0, 20, 40, 60, 80, 100], title_text="Score")
        fig_dims.update_yaxes(autorange="reversed")
        fig_dims.update_layout(title="FSI Dimensions (Block Summary)", margin=dict(l=60, r=40, t=50, b=40), height=300)
        dims_graph = dcc.Graph(figure=fig_dims, config={"displayModeBar": False})

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
                style_table={"overflowX": "auto", "maxHeight": "500px", "overflowY": "auto"},
                style_cell={"textAlign": "center", "padding": "6px", "fontSize": "13px"},
                style_header={"fontWeight": "bold", "backgroundColor": "#f2f2f2"},
                style_data_conditional=[
                    {"if": {"filter_query": "{Score} >= 75", "column_id": "Score"}, "backgroundColor": "#c93c3c", "color": "white"},
                    {"if": {"filter_query": "{Score} >= 50 && {Score} < 75", "column_id": "Score"}, "backgroundColor": "#e79c42", "color": "black"},
                    {"if": {"filter_query": "{Score} > 0 && {Score} < 50", "column_id": "Score"}, "backgroundColor": "#7bb7b3", "color": "black"},
                    {"if": {"filter_query": "{Mean} >= 75", "column_id": "Mean"}, "backgroundColor": "#c93c3c", "color": "white"},
                    {"if": {"filter_query": "{Mean} >= 50 && {Mean} < 75", "column_id": "Mean"}, "backgroundColor": "#e7b64a", "color": "black"},
                    {"if": {"filter_query": "{Mean} > 0 && {Mean} < 50", "column_id": "Mean"}, "backgroundColor": "#a8c29a", "color": "black"},
                ],
            )
        else:
            indicator_table = html.P("No indicator score data available for this block.")

        bottom_row = dbc.Row(
            [
                dbc.Col(section_card("Block-Level Susceptibility Dimensions", dims_graph), width=6),
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
                page_footer(),
            ]
        )

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
                html.Ul([html.Li(point) for point in advisory_points], style={"fontSize": "14px", "marginBottom": "10px"}),
                html.P(advisory_overall, style={"fontSize": "14px", "marginBottom": "0"}),
            ]
        )

    @app.callback(
        Output("block-page-body", "children"),
        [Input("block-camp-dropdown", "value"), Input("block-block-dropdown", "value")],
    )
    def render_block_page_body(selected_camp, selected_block):
        if not selected_camp:
            return html.P("Please select a camp.", style={"fontStyle": "italic"})
        if not selected_block:
            return html.P("Please select a block.", style={"fontStyle": "italic"})

        return build_block_level_content(selected_camp, selected_block)

    @app.callback(
        Output("block-fri-content", "children"),
        [
            Input("block-fri-tabs", "value"),
            Input("block-camp-dropdown", "value"),
            Input("block-block-dropdown", "value"),
        ],
    )
    def render_block_fri_tab(active_tab, camp_name, block_name):
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
            centroids = camp_all.groupby("Block")[["Latitude", "Longitude"]].mean().reset_index()

            block_stats = (
                camp_all
                .groupby("Block")[["Environment", "Fuel", "Behaviour", "Response"]]
                .mean()
                .reset_index()
                .merge(centroids, on="Block", how="left")
            )
            block_stats["FSI"] = (
                block_stats["Environment"] +
                block_stats["Fuel"] +
                block_stats["Behaviour"] +
                block_stats["Response"]
            ) / 4.0
            block_stats["FWI"] = block_stats.apply(
                lambda r: round(get_fwi_xclim(r["Latitude"], r["Longitude"], date_for=today_iso), 1),
                axis=1,
            )
            block_stats["FRI"] = compute_fri(block_stats["FSI"], block_stats["FWI"])
            block_stats["FRI_Class"] = block_stats["FRI"].apply(categorize_fri)

            df = block_stats.sort_values("FRI", ascending=False).reset_index(drop=True)

            risk_to_color_fri = {
                "Low risk": "green",
                "Moderate risk": "orange",
                "High risk": "red",
                "Extreme risk": "darkred",
            }
            colors = ["#1AAB48" if b == block_name else "#0033A0" for b in df["Block"]]
            text_colors = [risk_to_color_fri[c] for c in df["FRI_Class"]]

            fig = px.bar(
                df,
                x="Block",
                y="FRI",
                text="FRI_Class",
                labels={"Block": "Block", "FRI": "Fire Risk Index"},
                title=f"Current FRI by Block in {camp_name}",
            )
            fig.update_traces(marker_color=colors, textposition="outside", textfont=dict(color=text_colors, size=11), showlegend=False)
            fig.update_layout(xaxis_tickangle=-45, plot_bgcolor="white", margin=dict(l=40, r=20, t=60, b=120), yaxis=dict(range=[0, max(100, float(df["FRI"].max()) + 10)]))
            return dcc.Graph(figure=fig, config={"displayModeBar": False})

        elif active_tab == "monthly":
            outlook_df = build_monthly_outlook_df(lat, lon, base_fsi=fsi_value, year=OUTLOOK_YEAR)
            outlook_df = outlook_df.sort_values("MonthNum").reset_index(drop=True)

            if outlook_df.empty:
                return html.P("Seasonal outlook data is unavailable.", style={"color": "red"})

            fri_bar = px.bar(
                outlook_df,
                x="Month",
                y="FRI",
                color="FRI_Risk",
                text="FRI_Risk",
                title=f"Projected Monthly Fire Risk Outlook – Block {block_name} ({OUTLOOK_YEAR})",
                labels={"FRI": "Projected Fire Risk Index"},
                category_orders={"Month": MONTH_ORDER},
                color_discrete_map={
                    "Low risk": "green",
                    "Moderate risk": "orange",
                    "High risk": "red",
                    "Extreme risk": "purple",
                },
                template="plotly_white",
            )

            fri_bar.update_traces(textposition="outside")
            fri_bar.update_yaxes(range=[0, max(100, float(outlook_df["FRI"].max()) + 10)])

            fri_heatmap = build_monthly_outlook_heatmap(
                outlook_df,
                value_col="FRI",
                risk_col="FRI_Risk",
                title=f"Monthly Fire Risk Outlook – Block {block_name} ({OUTLOOK_YEAR})",
            )

            narrative = build_monthly_fri_narrative(block_name, outlook_df, year=OUTLOOK_YEAR)

            return html.Div(
                [
                    dcc.Graph(figure=fri_bar, config={"displayModeBar": False}),
                    dcc.Graph(figure=fri_heatmap, config={"displayModeBar": False}),
                    narrative,
                ]
            )

        else:
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
            fig.update_yaxes(range=[0, max(100, float(forecast_df["FRI"].max()) + 10)], title="Projected Fire Risk Index")

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

    @app.callback(
        Output("block-fwi-content", "children"),
        [
            Input("block-fwi-tabs", "value"),
            Input("block-camp-dropdown", "value"),
            Input("block-block-dropdown", "value"),
        ],
    )
    def render_block_fwi_tab(active_tab, camp_name, block_name):
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
            (dims_mean["Environment"] +
            dims_mean["Fuel"] +
            dims_mean["Behaviour"] +
            dims_mean["Response"]) / 4
        )

        lat = block_data["Latitude"].mean()
        lon = block_data["Longitude"].mean()
        today_iso = date.today().isoformat()

        if active_tab == "current":
            centroids = camp_all.groupby("Block")[["Latitude", "Longitude"]].mean().reset_index()
            records = []

            for _, r in centroids.iterrows():
                fwi_b = math.ceil(get_fwi_xclim(r["Latitude"], r["Longitude"], date_for=today_iso))
                records.append({"Block": r["Block"], "FWI": fwi_b, "Risk": categorize_fwi(fwi_b)})

            df = pd.DataFrame(records).sort_values("FWI", ascending=False).reset_index(drop=True)

            risk_to_color = {
                "Low fire danger": "green",
                "Moderate fire danger": "goldenrod",
                "High fire danger": "orange",
                "Severe fire danger": "red",
            }
            colors = ["#1AAB48" if b == block_name else "#0033A0" for b in df["Block"]]
            text_colors = df["Risk"].map(risk_to_color)

            fig = px.bar(
                df,
                x="Block",
                y="FWI",
                text="Risk",
                labels={"Block": "Block", "FWI": "Fire Weather Index"},
                title=f"Current FWI by Block in {camp_name}",
            )
            fig.update_traces(marker_color=colors, textposition="outside", textfont=dict(color=text_colors, size=11), showlegend=False)
            fig.update_layout(xaxis_tickangle=-45, plot_bgcolor="white", margin=dict(l=40, r=20, t=60, b=120), yaxis=dict(range=[0, max(100, float(df["FWI"].max()) + 10)]))
            return dcc.Graph(figure=fig, config={"displayModeBar": False})

        elif active_tab == "monthly":
            outlook_df = build_monthly_outlook_df(lat, lon, base_fsi=fsi_value, year=OUTLOOK_YEAR)
            outlook_df = outlook_df.sort_values("MonthNum").reset_index(drop=True)

            if outlook_df.empty:
                return html.P("Seasonal outlook data is unavailable.", style={"color": "red"})

            fwi_bar = px.bar(
                outlook_df,
                x="Month",
                y="FWI",
                color="FWI_Risk",
                text="FWI_Risk",
                title=f"Projected Monthly Fire Weather Outlook – Block {block_name} ({OUTLOOK_YEAR})",
                labels={"FWI": "Fire Weather Index"},
                category_orders={"Month": MONTH_ORDER},
                color_discrete_map={
                    "Low fire danger": "green",
                    "Moderate fire danger": "goldenrod",
                    "High fire danger": "orange",
                    "Severe fire danger": "red",
                },
                template="plotly_white",
            )

            fwi_bar.update_traces(textposition="outside")
            fwi_bar.update_yaxes(range=[0, max(100, float(outlook_df["FWI"].max()) + 10)])

            fwi_heatmap = build_monthly_outlook_heatmap(
                outlook_df,
                value_col="FWI",
                risk_col="FWI_Risk",
                title=f"Monthly Fire Weather Outlook – Block {block_name} ({OUTLOOK_YEAR})",
            )

            narrative = build_monthly_fwi_narrative(block_name, outlook_df, year=OUTLOOK_YEAR)

            return html.Div(
                [
                    dcc.Graph(figure=fwi_bar, config={"displayModeBar": False}),
                    dcc.Graph(figure=fwi_heatmap, config={"displayModeBar": False}),
                    narrative,
                ]
            )

        else:
            forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=float(fsi_value))

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
            fig.update_yaxes(range=[0, max(100, float(forecast_df["FWI"].max()) + 10)], title="Fire Weather Index")

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

    @app.callback(
        [Output("contact-collapse", "is_open"), Output("contact-content", "children")],
        [Input("contact-toggle", "n_clicks"), Input("camp-dropdown", "value")],
        [State("contact-collapse", "is_open")],
    )
    def toggle_and_populate_contact(n_clicks, selected_camp, is_open):
        if not n_clicks:
            return False, dash.no_update

        row = response_details.loc[response_details.CampName == selected_camp]
        if row.empty:
            return not is_open, html.P("No contact info available for this camp.")

        row = row.iloc[0]
        content = html.Div(
            [
                html.P([html.Strong("Site-Management focal: "), row["SM focal(Name and Mobile No)"]]),
                html.P([html.Strong("Sector Focals: "), row["Sector Focals(Name and Mobile No)"]]),
                html.P([html.Strong("DMU Lead: "), row["DMU Lead(Name and Mobile No)"]]),
                html.P([html.Strong("Infrastructure: "), row["List of infrastructure"]]),
            ],
            style={"fontSize": "14px"},
        )
        return not is_open, content