import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, html

from fire_risk.legacy.data import geojson_data
from fire_risk.services.common import current_camp_summary


def register_callbacks(app):
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
        [Input("overview-severity-filter", "value"), Input("weather-refresh-interval", "n_intervals")],
    )
    def filter_overview(sev, _n_intervals):
        dff = current_camp_summary().copy()

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

