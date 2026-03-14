import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html

from fire_risk.legacy.fwi_fri import categorize_fri, categorize_fwi, get_monthly_fwi_xclim

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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

    fig = go.Figure(data=go.Heatmap(
        z=[cal_df["RiskScore"].tolist()],
        x=cal_df["DayLabel"].tolist(),
        y=["Outlook"],
        text=[[f"{row['Date']}<br>{value_col}: {row[value_col]}<br>{risk_col}: {row[risk_col]}" for _, row in cal_df.iterrows()]],
        hoverinfo="text",
        colorscale=[[0.00, "#22c55e"], [0.25, "#facc15"], [0.50, "#f97316"], [0.75, "#dc2626"], [1.00, "#7e22ce"]],
        zmin=1,
        zmax=4,
        showscale=False,
    ))
    fig.update_layout(title=title, height=180, margin=dict(l=20, r=20, t=50, b=20), xaxis=dict(title="", side="top"), yaxis=dict(title="", showticklabels=False), plot_bgcolor="white", paper_bgcolor="white")
    return fig


def build_monthly_outlook_df(lat, lon, base_fsi, year=2026):
    monthly_fwi = get_monthly_fwi_xclim(lat, lon, year)
    df = pd.DataFrame({"MonthNum": list(range(1, 13)), "Month": MONTH_LABELS, "FWI": monthly_fwi})
    df["FWI"] = pd.to_numeric(df["FWI"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0).round(1)
    df["FRI"] = (float(base_fsi) * (1 + df["FWI"] / 100.0)).round(1)
    df["FWI_Risk"] = df["FWI"].apply(categorize_fwi)
    df["FRI_Risk"] = df["FRI"].apply(categorize_fri)
    return df


def build_monthly_outlook_heatmap(df_monthly, value_col, risk_col, title):
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
    text_vals = [[f"{row['Month']} {value_col}: {row[value_col]}<br>{risk_col}: {row[risk_col]}" for _, row in df_monthly.iterrows()]]
    fig = go.Figure(data=go.Heatmap(
        z=z_vals,
        x=df_monthly["Month"].tolist(),
        y=[value_col],
        text=text_vals,
        hoverinfo="text",
        colorscale=[[0.00, "#22c55e"], [0.25, "#facc15"], [0.50, "#f97316"], [0.75, "#dc2626"], [1.00, "#7e22ce"]],
        zmin=1,
        zmax=4,
        showscale=False,
    ))
    fig.update_layout(title=title, height=170, margin=dict(l=20, r=20, t=45, b=20), xaxis=dict(title="", side="top"), yaxis=dict(title="", showticklabels=True), plot_bgcolor="white", paper_bgcolor="white")
    return fig


def build_monthly_outlook_narrative(block_name, df_monthly, year=2026):
    if df_monthly.empty:
        return html.P("No seasonal outlook data available.")

    peak_fwi = df_monthly.loc[df_monthly["FWI"].idxmax()]
    peak_fri = df_monthly.loc[df_monthly["FRI"].idxmax()]
    high_fwi_months = df_monthly[df_monthly["FWI_Risk"].isin(["High fire danger", "Severe fire danger"])]["Month"].tolist()
    high_fri_months = df_monthly[df_monthly["FRI_Risk"].isin(["High risk", "Extreme risk"])]["Month"].tolist()

    return html.Div([
        html.H5(f"Seasonal Outlook Summary ({year})", style={"fontWeight": "bold"}),
        html.P(f"For Block {block_name}, the highest projected Fire Weather Index (FWI) is expected in {peak_fwi['Month']} ({peak_fwi['FWI']}, {peak_fwi['FWI_Risk']}).", style={"fontSize": "14px"}),
        html.P(f"The highest projected Fire Risk Index (FRI) is expected in {peak_fri['Month']} ({peak_fri['FRI']}, {peak_fri['FRI_Risk']}).", style={"fontSize": "14px"}),
        html.P(f"Months with elevated fire-weather concern: {', '.join(high_fwi_months) if high_fwi_months else 'None' }.", style={"fontSize": "14px"}),
        html.P(f"Months with elevated operational fire-risk concern: {', '.join(high_fri_months) if high_fri_months else 'None' }.", style={"fontSize": "14px"}),
        html.P("Use this seasonal view for preparedness planning, awareness campaigns, equipment checks, and scheduling of prevention activities ahead of higher-risk months.", style={"fontSize": "14px"}),
    ])

def build_monthly_fwi_narrative(block_name, df_monthly, year=2026):
    if df_monthly.empty:
        return html.P("No seasonal fire weather outlook data available.")

    peak_fwi = df_monthly.loc[df_monthly["FWI"].idxmax()]
    low_fwi = df_monthly.loc[df_monthly["FWI"].idxmin()]
    high_fwi_months = df_monthly[
        df_monthly["FWI_Risk"].isin(["High fire danger", "Severe fire danger"])
    ]["Month"].tolist()

    return html.Div([
        html.H5(f"Seasonal Fire Weather Outlook Summary ({year})", style={"fontWeight": "bold"}),
        html.P(
            f"For Block {block_name}, the highest projected Fire Weather Index (FWI) is expected in "
            f"{peak_fwi['Month']} ({peak_fwi['FWI']}, {peak_fwi['FWI_Risk']}).",
            style={"fontSize": "14px"}
        ),
        html.P(
            f"The lowest projected Fire Weather Index (FWI) is expected in "
            f"{low_fwi['Month']} ({low_fwi['FWI']}, {low_fwi['FWI_Risk']}).",
            style={"fontSize": "14px"}
        ),
        html.P(
            f"Months with elevated fire-weather concern: "
            f"{', '.join(high_fwi_months) if high_fwi_months else 'None'}.",
            style={"fontSize": "14px"}
        ),
        html.P(
            "Use this seasonal view to identify when weather conditions are more likely to support fire ignition and spread.",
            style={"fontSize": "14px"}
        ),
    ])


def build_monthly_fri_narrative(block_name, df_monthly, year=2026):
    if df_monthly.empty:
        return html.P("No seasonal fire risk outlook data available.")

    peak_fri = df_monthly.loc[df_monthly["FRI"].idxmax()]
    low_fri = df_monthly.loc[df_monthly["FRI"].idxmin()]
    high_fri_months = df_monthly[
        df_monthly["FRI_Risk"].isin(["High risk", "Extreme risk"])
    ]["Month"].tolist()

    return html.Div([
        html.H5(f"Seasonal Fire Risk Outlook Summary ({year})", style={"fontWeight": "bold"}),
        html.P(
            f"For Block {block_name}, the highest projected Fire Risk Index (FRI) is expected in "
            f"{peak_fri['Month']} ({peak_fri['FRI']}, {peak_fri['FRI_Risk']}).",
            style={"fontSize": "14px"}
        ),
        html.P(
            f"The lowest projected Fire Risk Index (FRI) is expected in "
            f"{low_fri['Month']} ({low_fri['FRI']}, {low_fri['FRI_Risk']}).",
            style={"fontSize": "14px"}
        ),
        html.P(
            f"Months with elevated operational fire-risk concern: "
            f"{', '.join(high_fri_months) if high_fri_months else 'None'}.",
            style={"fontSize": "14px"}
        ),
        html.P(
            "Use this seasonal view for preparedness planning, awareness campaigns, equipment checks, and prevention actions ahead of higher-risk months.",
            style={"fontSize": "14px"}
        ),
    ])
