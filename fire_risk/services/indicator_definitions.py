from pathlib import Path

import pandas as pd

APP_BASE_DIR = Path(__file__).resolve().parents[2]
DEFINITIONS_FILE = APP_BASE_DIR / "fire_indicator_definitions.csv"


def load_indicator_definitions_df():
    print("Looking for definitions file at:", DEFINITIONS_FILE)
    print("File exists:", DEFINITIONS_FILE.exists())

    try:
        df = pd.read_csv(DEFINITIONS_FILE, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(DEFINITIONS_FILE, encoding="latin1")
    except Exception as e:
        print("ERROR reading definitions CSV:", repr(e))
        return pd.DataFrame(
            columns=["code", "section", "parent_code", "question", "description", "rationale", "status"]
        )

    print("Definitions CSV loaded successfully.")
    print("Original columns:", list(df.columns))
    print("Row count before cleaning:", len(df))

    df.columns = [str(c).strip().lower() for c in df.columns]
    print("Normalized columns:", list(df.columns))

    expected = ["code", "section", "parent_code", "question", "description", "rationale", "status"]
    for col in expected:
        if col not in df.columns:
            df[col] = ""

    for col in expected:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df = df[df["code"] != ""].copy()

    print("Row count after keeping nonblank code:", len(df))
    print("Sample codes:", df["code"].head(10).tolist())

    return df


INDICATOR_DEFINITIONS_DF = load_indicator_definitions_df()

INDICATOR_GROUPS = {
    "ENV_001": ["ENV_001"],
    "ENV_002": ["ENV_002"],
    "ENV_003": ["ENV_003a", "ENV_003b"],
    "ENV_004": ["ENV_004"],
    "FUEL_001": ["FUEL_001"],
    "FUEL_002": ["FUEL_002a", "FUEL_002b"],
    "FUEL_003": ["FUEL_003a", "FUEL_003b"],
    "BEH_001": ["BEH_001a", "BEH_001b"],
    "BEH_002": ["BEH_002"],
    "BEH_003": ["BEH_003"],
    "BEH_004": ["BEH_004"],
    "BEH_005": ["BEH_005"],
    "BEH_006": ["BEH_006a", "BEH_006b"],
    "BEH_007": ["BEH_007"],
    "BEH_008": ["BEH_008"],
    "RES_001": ["RES_001a", "RES_001b", "RES_001c", "RES_001d", "RES_001e", "RES_001f", "RES_001g"],
    "RES_002": ["RES_002"],
    "RES_003": ["RES_003a", "RES_003b", "RES_003c", "RES_003d"],
    "RES_005": ["RES_005a", "RES_005b", "RES_005c"],
}


def build_indicator_score_table(selected_df, full_df):
    rows = []
    for indicator, raw_cols in INDICATOR_GROUPS.items():
        existing_selected = [c for c in raw_cols if c in selected_df.columns]
        existing_full = [c for c in raw_cols if c in full_df.columns]
        if not existing_selected or not existing_full:
            continue

        selected_vals = selected_df[existing_selected].apply(pd.to_numeric, errors="coerce")
        full_vals = full_df[existing_full].apply(pd.to_numeric, errors="coerce")

        selected_score = selected_vals.mean(axis=1, skipna=True).dropna()
        full_score = full_vals.mean(axis=1, skipna=True).dropna()
        if selected_score.empty:
            continue

        rows.append({
            "Indicator": indicator,
            "Score": round(float(selected_score.mean()), 2),
            "Mean": round(float(full_score.mean()), 6) if not full_score.empty else None,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["Rank"] = out["Score"].rank(method="dense", ascending=False).astype(int)
    out = out.sort_values("Indicator").reset_index(drop=True)
    return out[["Indicator", "Score", "Rank", "Mean"]]
