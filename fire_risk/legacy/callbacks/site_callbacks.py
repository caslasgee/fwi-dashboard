from datetime import date

import dash
import numpy as np
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html
import math

from fire_risk.legacy.data import cleaned_data, geojson_data
from fire_risk.legacy.fwi_fri import (
    build_current_risk_narrative,
    build_current_weather_narrative,
    build_forecast_narrative,
    build_monthly_risk_narrative,
    categorize_fri,
    categorize_fwi,
    classify_fsi,
    get_14day_fire_forecast,
    get_monthly_fwi_xclim,
    get_weather_noon,
)
from fire_risk.services.common import OUTLOOK_YEAR, current_camp_summary
from fire_risk.services.outlook_helpers import build_fire_risk_outlook_calendar


def register_callbacks(app):
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

        if active_tab == "monthly":
            year = OUTLOOK_YEAR - 1
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
                title=f"Seasonal Fire Weather Outlook ({year}) for {selected_camp}",
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
                camp_df[["CampName", "FWI"]]
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
        [Input("camp-dropdown", "value"), Input("site-fri-tabs", "value"), Input("weather-refresh-interval", "n_intervals")],
    )
    def render_fri_tab(selected_camp, active_tab, _n_intervals):
        camp_df = current_camp_summary()
        row = camp_df[camp_df["CampName"] == selected_camp]
        if row.empty:
            return dash.no_update
        row = row.iloc[0]

        lat, lon = row["Latitude"], row["Longitude"]
        fsi_val = float(row["FSI_Calculated"])

        if active_tab == "monthly":
            year = OUTLOOK_YEAR - 1
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
                title=f"Seasonal Fire Risk Outlook ({year}) for {selected_camp}",
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
                camp_df[["CampName", "FRI", "FRI_Class"]]
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
        [Input("camp-dropdown", "value"), Input("weather-refresh-interval", "n_intervals")],
    )
    def update_dashboard(selected_camp, _n_intervals):
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

        live_camp_summary = current_camp_summary()
        camp_row = live_camp_summary.loc[live_camp_summary["CampName"] == selected_camp]
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
