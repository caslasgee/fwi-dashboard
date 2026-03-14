from datetime import date
import math

import dash
import numpy as np
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html

from fire_risk.legacy.data import cleaned_data, geojson_data
from fire_risk.legacy.fwi_fri import (
    build_current_risk_narrative,
    build_current_weather_narrative,
    build_forecast_narrative,
    categorize_fri,
    categorize_fwi,
    classify_fsi,
    compute_fri,
    get_14day_fire_forecast,
)
from fire_risk.services.common import OUTLOOK_YEAR, current_camp_summary
from fire_risk.services.outlook_helpers import (
    build_fire_risk_outlook_calendar,
    build_monthly_fri_narrative,
    build_monthly_fwi_narrative,
    build_monthly_outlook_df,
)

MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def register_callbacks(app):
    # -------------------------------------------------------------------
    # SITE-LEVEL FWI TABS
    # -------------------------------------------------------------------
    @app.callback(
        [Output("site-fwi-content", "children"), Output("site-fwi-narrative", "children")],
        [Input("camp-dropdown", "value"), Input("site-fwi-tabs", "value"), Input("weather-refresh-interval", "n_intervals")],
    )
    def render_fwi_tab(selected_camp, active_tab, _n_intervals):
        camp_df = current_camp_summary()
        row = camp_df[camp_df["CampName"] == selected_camp]
        if row.empty:
            return dash.no_update, dash.no_update

        row = row.iloc[0]
        lat, lon = row["Latitude"], row["Longitude"]
        camp_fsi = float(row["FSI_Calculated"])

        if active_tab == "monthly":
            outlook_df = build_monthly_outlook_df(lat, lon, base_fsi=camp_fsi, year=OUTLOOK_YEAR)
            outlook_df = outlook_df.sort_values("MonthNum").reset_index(drop=True)

            if outlook_df.empty:
                return html.P("Seasonal outlook data is unavailable.", style={"color": "red"}), dash.no_update

            fig = px.bar(
                outlook_df,
                x="Month",
                y="FWI",
                color="FWI_Risk",
                text="FWI_Risk",
                title=f"Projected Monthly Fire Weather Outlook – {selected_camp} ({OUTLOOK_YEAR})",
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
            fig.update_traces(textposition="outside")
            fig.update_yaxes(range=[0, max(100, float(outlook_df["FWI"].max()) + 10)])

            narrative = build_monthly_fwi_narrative(selected_camp, outlook_df, year=OUTLOOK_YEAR)
            return dcc.Graph(figure=fig, config={"displayModeBar": False}), narrative

        elif active_tab == "current":
            df = (
                camp_df[["CampName", "FWI"]]
                .assign(FWI=lambda d: d.FWI.round(0).astype(int))
                .sort_values("FWI", ascending=False)
                .reset_index(drop=True)
            )
            rank = int(df.index[df.CampName == selected_camp][0]) + 1
            total = len(df)

            colors = ["#1AAB48" if c == selected_camp else "#0033A0" for c in df["CampName"]]
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
                template="plotly_white",
            )
            fig.update_traces(marker_color=colors, textposition="outside", textfont=dict(color=text_colors, size=12), showlegend=False)
            fig.update_layout(xaxis_tickangle=-45, plot_bgcolor="white", margin=dict(l=40, r=20, t=60, b=120))
            fig.update_yaxes(range=[0, max(100, float(df["FWI"].max()) + 10)])

            narrative = build_current_weather_narrative(selected_camp, df.copy())
            return dcc.Graph(figure=fig, config={"displayModeBar": False}), narrative

        else:
            forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=camp_fsi)
            if forecast_df.empty:
                return html.P("Forecast data is currently unavailable.", style={"color": "red"}), dash.no_update

            fig = px.line(
                forecast_df,
                x="Date",
                y="FWI",
                color="FWI_Risk",
                markers=True,
                title=f"14-Day Stateful Fire Weather Index Forecast for {selected_camp}",
                labels={"FWI": "Fire Weather Index", "FWI_Risk": "Danger Level"},
                color_discrete_map={
                    "Low fire danger": "green",
                    "Moderate fire danger": "goldenrod",
                    "High fire danger": "orange",
                    "Severe fire danger": "red",
                },
            )
            fig.update_traces(mode="lines+markers")
            fig.update_yaxes(range=[0, max(100, float(forecast_df["FWI"].max()) + 10)], title="Fire Weather Index")

            calendar_fig = build_fire_risk_outlook_calendar(
                forecast_df,
                value_col="FWI",
                risk_col="FWI_Risk",
                title=f"14-Day Fire Weather Outlook Calendar – {selected_camp}",
            )

            forecast_df_narr = forecast_df.copy()
            forecast_df_narr["Risk"] = forecast_df_narr["FWI_Risk"]
            narrative = build_forecast_narrative(selected_camp, forecast_df_narr, value_col="FWI", index_name="Fire Weather Index")

            content = html.Div([
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                dcc.Graph(figure=calendar_fig, config={"displayModeBar": False}),
            ])
            return content, narrative

    # -------------------------------------------------------------------
    # SITE-LEVEL FRI TABS
    # -------------------------------------------------------------------
    @app.callback(
        [Output("site-fri-content", "children"), Output("site-fri-narrative", "children")],
        [
            Input("camp-dropdown", "value"),
            Input("site-fri-tabs", "value"),
            Input("weather-refresh-interval", "n_intervals"),
        ],
    )
    def render_fri_tab(selected_camp, active_tab, _n_intervals):
        camp_df = current_camp_summary()
        row = camp_df[camp_df["CampName"] == selected_camp]

        if row.empty:
            return dash.no_update, dash.no_update

        row = row.iloc[0]
        lat, lon = row["Latitude"], row["Longitude"]
        camp_fsi = float(row["FSI_Calculated"])
        fsi_val = float(row["FSI_Calculated"])

        if active_tab == "monthly":
            outlook_df = build_monthly_outlook_df(
                lat,
                lon,
                base_fsi=fsi_val,
                year=OUTLOOK_YEAR,
            )
            outlook_df = outlook_df.sort_values("MonthNum").reset_index(drop=True)

            if outlook_df.empty:
                return (
                    html.P("Seasonal outlook data is unavailable.", style={"color": "red"}),
                    dash.no_update,
                )

            fri_bar = px.bar(
                outlook_df,
                x="Month",
                y="FRI",
                color="FRI_Risk",
                text="FRI_Risk",
                title=f"Projected Monthly Fire Risk Outlook – {selected_camp} ({OUTLOOK_YEAR})",
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

            narrative = build_monthly_fri_narrative(
                selected_camp,
                outlook_df,
                year=OUTLOOK_YEAR,
            )

            return dcc.Graph(figure=fri_bar, config={"displayModeBar": False}), narrative

        elif active_tab == "current":
            df = (
                camp_df[["CampName", "FRI", "FRI_Class"]]
                .sort_values("FRI", ascending=False)
                .reset_index(drop=True)
            )
            df["FRI"] = np.ceil(df["FRI"]).astype(int)

            rank = int(df.index[df.CampName == selected_camp][0]) + 1
            total = len(df)

            colors = ["#1AAB48" if c == selected_camp else "#0033A0" for c in df["CampName"]]

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
            fig.update_yaxes(range=[0, max(100, float(df["FRI"].max()) + 10)])

            narrative = build_current_risk_narrative(selected_camp, df.copy())
            return dcc.Graph(figure=fig, config={"displayModeBar": False}), narrative

        else:  # forecasted
            forecast_df = get_14day_fire_forecast(lat, lon, base_fsi=fsi_val)

            if forecast_df.empty:
                return (
                    html.P("Forecast data is currently unavailable.", style={"color": "red"}),
                    dash.no_update,
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
            fig.update_yaxes(range=[0, max(100, float(forecast_df["FRI"].max()) + 10)], title="Projected Fire Risk Index")

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

            content = html.Div(
                [
                    dcc.Graph(figure=fig, config={"displayModeBar": False}),
                    dcc.Graph(figure=calendar_fig, config={"displayModeBar": False}),
                ]
            )

            return content, narrative

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
        [Input("camp-dropdown", "value"), Input("weather-refresh-interval", "n_intervals")],
    )
    def update_dashboard(selected_camp, _n_intervals):
        camp_data = cleaned_data[cleaned_data["CampName"] == selected_camp]
        if camp_data.empty:
            return "No data available", "-", "-", "-", {}, {}, []

        live_camp_summary = current_camp_summary()
        camp_row = live_camp_summary.loc[live_camp_summary["CampName"] == selected_camp]
        if camp_row.empty:
            return "No summary data", "-", "-", "-", {}, {}, []

        camp = camp_row.iloc[0]

        assessment_text = "N/A"
        if "assessment_date" in camp_data.columns:
            assessment_series = pd.to_datetime(camp_data["assessment_date"], errors="coerce").dropna()
            if not assessment_series.empty:
                min_date = assessment_series.min().date().isoformat()
                max_date = assessment_series.max().date().isoformat()
                assessment_text = min_date if min_date == max_date else f"{min_date} to {max_date}"

        population_text = "N/A"
        pop_col = "ENV_003a"
        if pop_col in camp_data.columns:
            site_pop = pd.to_numeric(camp_data[pop_col], errors="coerce").fillna(0).sum()
            population_text = f"{site_pop:,.0f}"

        site_container = html.Div([
            html.P([html.Strong("Site name: "), selected_camp]),
            html.P([html.Strong("Assessment date: "), assessment_text]),
            html.P([html.Strong("Site population: "), population_text]),
        ], style={"fontSize": "14px"})

        fsi_value = math.ceil(camp["FSI_Calculated"])
        fsi_class = classify_fsi(fsi_value)
        fsi_text = html.Div([
            html.H2(f"{fsi_value} – {fsi_class}", className="mt-1 mb-0"),
            html.P(f"FSI Severity: {fsi_class}", style={"fontSize": "14px", "margin": "0", "color": "#555"}),
        ])

        today_iso = date.today().isoformat()
        fwi_value = int(round(camp["FWI"]))
        fri_value = int(round(camp["FRI"]))
        fri_severity = categorize_fri(fri_value)

        fwi_text = html.Div([
            html.H2(f"{fwi_value} – {categorize_fwi(fwi_value).split()[0]}", className="mt-1 mb-0"),
            html.P(f"Weather reference: {today_iso} (noon conditions)", style={"fontSize": "14px", "margin": "0", "color": "#555"}),
        ])

        fri_text = html.Div([
            html.H2(f"{fri_value} – {fri_severity.split()[0]}", className="mt-1 mb-0"),
            html.P(f"FRI Severity: {fri_severity}", style={"fontSize": "14px", "margin": "0", "color": "#555"}),
        ])

        block_means = camp_data.groupby("Block")[["Environment", "Fuel", "Behaviour", "Response"]].mean().reset_index()
        melted = block_means.melt(id_vars="Block", var_name="Dimension", value_name="Score")
        melted["Score"] = melted["Score"].round(0).astype(int)

        block_bar_fig = px.bar(melted, x="Block", y="Score", color="Dimension", barmode="group", text="Score", template="plotly_white")
        block_bar_fig.update_traces(texttemplate="%{text}", textposition="outside")

        selected_features = []
        if geojson_data is not None:
            selected_features = [feat for feat in geojson_data["features"] if feat.get("properties", {}).get("CampName") == selected_camp]

        if selected_features:
            selected_geojson = {"type": "FeatureCollection", "features": selected_features}
            coords = selected_features[0]["geometry"]["coordinates"][0]
            lons, lats = zip(*coords)
            centre = {"lat": (max(lats) + min(lats)) / 2, "lon": (max(lons) + min(lons)) / 2}
            df_sel = pd.DataFrame([{"CampName": selected_camp, "FRI": fri_value}])

            map_fig = px.choropleth_mapbox(
                df_sel,
                geojson=selected_geojson,
                locations="CampName",
                featureidkey="properties.CampName",
                color="FRI",
                range_color=(0, max(100, float(fri_value) + 5)),
                color_continuous_scale="OrRd",
                center=centre,
                zoom=11,
                opacity=0.6,
                mapbox_style="carto-positron",
                hover_name="CampName",
                hover_data={"FRI": False},
            )
            map_fig.update_traces(
                hovertemplate=f"<b>%{{hovertext}}</b><br>FRI: {fri_value} – {fri_severity}<extra></extra>"
            )
            map_fig.update_layout(
                margin={"l": 0, "r": 0, "t": 30, "b": 0},
                uirevision=selected_camp
            )
        else:
            map_fig = {}

        table_df = camp_data[["Block", "FSI_Calculated", "FSI_Class"]].copy()
        table_df["FSI_Calculated"] = table_df["FSI_Calculated"].round(0).astype(int)
        table_df = table_df.rename(columns={"Block": "Site Block", "FSI_Calculated": "FSI Score"})
        table_data = table_df.to_dict("records")

        return site_container, fsi_text, fwi_text, fri_text, block_bar_fig, map_fig, table_data

    # -------------------------------------------------------------------
    # WINDY IFRAME (SITE-LEVEL)
    # -------------------------------------------------------------------
    @app.callback(Output("windy-iframe", "src"), Input("camp-dropdown", "value"))
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
