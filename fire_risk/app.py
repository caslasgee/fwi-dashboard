"""
Feature-complete Fire Risk Dash app (wrapper).
"""
from fire_risk.legacy.app import app  # import your Dash instance

# Some deployments expect `server` (WSGI). Create it safely.
server = getattr(app, "server", app)