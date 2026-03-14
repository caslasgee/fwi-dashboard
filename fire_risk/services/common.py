from datetime import date

from fire_risk.legacy.data import get_live_camp_summary

OUTLOOK_YEAR = date.today().year
OUTLOOK_LABEL = f"Seasonal Outlook {OUTLOOK_YEAR}"


def current_camp_summary(force_refresh: bool = False):
    return get_live_camp_summary(force_refresh=force_refresh)
