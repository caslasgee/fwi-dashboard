# config.py

"""
Central place for thresholds and tunable parameters.
Don't tweak except there is changes in the FSI dimensions parameter.
"""

# FSI classification bands
FSI_URGENT_THRESHOLD = 67   # >= 67 → "Urgent"
FSI_HIGH_THRESHOLD = 33     # >= 33 → "High", else "Moderate"

# FRI risk bands
FRI_LOW_MAX = 50            # < 50  → Low
FRI_MODERATE_MAX = 75       # < 75  → Moderate
FRI_HIGH_MAX = 100          # < 100 → High, else Extreme

# FWI danger bands
FWI_LOW_MAX = 10            # < 10  → Low fire danger
FWI_MODERATE_MAX = 20       # < 20  → Moderate fire danger
FWI_HIGH_MAX = 35           # < 35  → High fire danger, else Severe