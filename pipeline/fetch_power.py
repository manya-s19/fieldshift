"""Pull real weather for every county from the NASA POWER API (no key needed)
and aggregate it to one row per county-season.

Output: data/raw/weather_season.csv and data/raw/county.csv

Usage:  python pipeline/fetch_power.py            # START_YEAR .. last full year
        python pipeline/fetch_power.py 2000 2026
"""
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fs.config import COUNTIES, HEAT_DAY_C, RAW, START_YEAR  # noqa: E402

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = "PRECTOTCORR,T2M_MAX,GWETROOT"   # rain mm/day, max temp C, root-zone soil wetness 0-1
FILL = -999.0


def fetch_point(lat, lon, start, end):
    r = requests.get(URL, timeout=120, params=dict(
        parameters=PARAMS, community="AG", latitude=lat, longitude=lon,
        start=f"{start}0101", end=f"{end}1231", format="JSON"))
    r.raise_for_status()
    series = r.json()["properties"]["parameter"]
    df = pd.DataFrame(series)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    return df.where(df > FILL + 1)          # POWER marks missing days with -999


def season_rows(fips, daily):
    rows = []
    for yr, d in daily.groupby(daily.index.year):
        grow = d[(d.index.month >= 4) & (d.index.month <= 9)]       # Apr-Sep growing season
        if grow["PRECTOTCORR"].notna().sum() < 150:                  # skip incomplete seasons
            continue
        rows.append(dict(
            fips=fips, year=yr,
            gs_precip=round(grow["PRECTOTCORR"].sum(), 1),
            gs_tmax=round(grow["T2M_MAX"].mean(), 2),
            heat_days=int((grow["T2M_MAX"] > HEAT_DAY_C).sum()),
            soil_wet_spring=round(d[d.index.month.isin([3, 4])]["GWETROOT"].mean(), 3),
            soil_wet_summer=round(d[d.index.month.isin([6, 7, 8])]["GWETROOT"].mean(), 3),
        ))
    return rows


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else START_YEAR
    end = int(sys.argv[2]) if len(sys.argv) > 2 else date.today().year - (date.today().month < 11)
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    for fips, name, lat, lon in COUNTIES:
        print(f"POWER  {name:<10} ({lat}, {lon})  {start}-{end}")
        rows += season_rows(fips, fetch_point(lat, lon, start, end))
        time.sleep(1)                        # be polite to the API
    pd.DataFrame(rows).to_csv(RAW / "weather_season.csv", index=False)
    pd.DataFrame(COUNTIES, columns=["fips", "name", "lat", "lon"]).to_csv(RAW / "county.csv", index=False)
    print(f"Wrote {len(rows)} county-seasons to {RAW / 'weather_season.csv'}")


if __name__ == "__main__":
    main()
