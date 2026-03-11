# Fire Risk Dashboard (Feature-complete package)

This package wraps your original (feature-complete) Dash app under a package structure.

## Run
1. Create/activate a Python environment with your existing dependencies:
   - dash, dash-bootstrap-components, pandas, numpy, plotly, requests, xarray, xclim

2. From this folder, run:
   ```bash
   python run_fire_risk.py
   ```

## Structure
- `fire_risk/legacy/` contains your original code with import-path fixes.
- `fire_risk/app.py` exports the Dash `app` and `server` objects.
- Data files are included alongside `run_fire_risk.py` for convenience.

## Notes
- Narratives that used Markdown inside `html.P` were patched to use `dcc.Markdown` where detected.
- A SQLite TTL cache is included at `fire_risk/services/cache.py` for future optimization work.
