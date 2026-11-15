"""Shared constants: region, crops, file locations."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "fieldshift.duckdb"

STATE = "KS"
STATE_NAME = "Kansas"
START_YEAR = 2000

# (fips, name, lat, lon) -- 14 Kansas counties spanning the dry west to the wetter east.
COUNTIES = [
    ("20181", "Sherman", 39.35, -101.72),
    ("20193", "Thomas", 39.35, -101.06),
    ("20171", "Scott", 38.48, -100.91),
    ("20055", "Finney", 38.04, -100.74),
    ("20057", "Ford", 37.69, -99.89),
    ("20009", "Barton", 38.48, -98.76),
    ("20151", "Pratt", 37.65, -98.74),
    ("20155", "Reno", 37.95, -98.09),
    ("20191", "Sumner", 37.24, -97.48),
    ("20113", "McPherson", 38.39, -97.65),
    ("20169", "Saline", 38.78, -97.65),
    ("20157", "Republic", 39.83, -97.65),
    ("20117", "Marshall", 39.78, -96.52),
    ("20013", "Brown", 39.83, -95.56),
]

CROPS = ["wheat", "corn", "sorghum", "soybeans"]
CROP_LABEL = {"wheat": "Winter wheat", "corn": "Corn", "sorghum": "Sorghum", "soybeans": "Soybeans"}

# Fixed colour per crop (colour follows the crop, never its rank).
CROP_COLOR = {"wheat": "#2a78d6", "corn": "#eb6834", "sorghum": "#1baf7a", "soybeans": "#eda100"}

# Cobweb phase thresholds (tune on history).
ACRE_Z_THRESHOLD = 0.75      # z-score of market acreage vs trailing mean
PRICE_CHG_THRESHOLD = 0.10   # prior-year price change
TRAIL_YEARS = 10             # window for "normal" acreage

RISK_AVERSION = 0.5          # score = p50 - RISK_AVERSION * (p50 - p10)
HEAT_DAY_C = 35.0
