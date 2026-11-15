"""Generate SYNTHETIC sample data so the app runs before real data is pulled.

Nothing here is a real observation. The numbers are simulated with roughly
Kansas-like magnitudes, and the simulation deliberately contains a cobweb
(farmers chase last year's price). Any backtest result on this data therefore
shows that the pipeline works, not that the idea works. Replace it with
fetch_power.py + fetch_nass.py output before quoting any number.

Usage:  python pipeline/make_sample_data.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fs.config import COUNTIES, CROPS, RAW, START_YEAR  # noqa: E402

END_YEAR = 2026
rng = np.random.default_rng(14)

# crop: (base yield in a mid-state county, long-run price $/bu, cost $/acre,
#        water sensitivity, heat sensitivity, base market acres in millions)
P = {
    "wheat":    dict(y=44, p=5.6,  c=150, water=0.35, heat=0.25, acres=46.0),
    "corn":     dict(y=120, p=4.4, c=300, water=1.00, heat=0.90, acres=90.0),
    "sorghum":  dict(y=78, p=4.1,  c=190, water=0.40, heat=0.30, acres=6.5),
    "soybeans": dict(y=40, p=10.4, c=200, water=0.75, heat=0.60, acres=84.0),
}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    years = list(range(START_YEAR, END_YEAR + 1))
    lons = np.array([c[3] for c in COUNTIES])
    east = (lons - lons.min()) / (lons.max() - lons.min())  # 0 = west, 1 = east

    # ---- weather: a statewide wet/dry signal plus county noise ----
    state_signal = rng.normal(0, 1, len(years))
    wrows = []
    for yi, yr in enumerate(years):
        for ci, (fips, *_rest) in enumerate(COUNTIES):
            z = 0.8 * state_signal[yi] + 0.6 * rng.normal()
            normal_precip = 290 + 330 * east[ci]                 # mm, Apr-Sep
            precip = max(90.0, normal_precip * (1 + 0.24 * z))
            tmax = 31.5 - 2.2 * east[ci] - 1.1 * z + rng.normal(0, 0.4)
            heat_days = max(0.0, 34 - 16 * east[ci] - 9 * z + rng.normal(0, 3))
            wet_spring = float(np.clip(0.46 + 0.14 * east[ci] + 0.06 * (0.6 * z + 0.8 * rng.normal()), 0.2, 0.9))
            wet_summer = float(np.clip(0.42 + 0.14 * east[ci] + 0.08 * z + rng.normal(0, 0.02), 0.15, 0.9))
            wrows.append(dict(fips=fips, year=yr, gs_precip=round(precip, 1), gs_tmax=round(tmax, 2),
                              heat_days=round(heat_days, 1), soil_wet_spring=round(wet_spring, 3),
                              soil_wet_summer=round(wet_summer, 3), zsig=z, east=east[ci]))
    weather = pd.DataFrame(wrows)

    # ---- county yields ----
    crows = []
    for r in weather.itertuples():
        for crop in CROPS:
            k = P[crop]
            place = 1 - k["water"] * 0.55 * (1 - r.east)        # thirsty crops suffer in the west
            trend = 1 + 0.008 * (r.year - START_YEAR)
            shock = k["water"] * 0.20 * r.zsig - k["heat"] * 0.004 * (r.heat_days - 26)
            y = k["y"] * place * trend * (1 + shock) * (1 + rng.normal(0, 0.06))
            crows.append(dict(fips=r.fips, crop=crop, year=r.year, yield_per_acre=round(max(y, 2.0), 1)))
    crop_year = pd.DataFrame(crows)

    # ---- market: acreage chases last year's price, price falls when acreage is high ----
    state_yield = crop_year.groupby(["crop", "year"]).yield_per_acre.mean().unstack(0)
    mrows = []
    for crop in CROPS:
        k = P[crop]
        ys = np.log(state_yield[crop] / (state_yield[crop].rolling(5, min_periods=1).mean()))
        world = 0.0
        prev_price, prev_prev = k["p"], k["p"]
        acre_dev = 0.0
        for yr in years:
            chase = np.log(prev_price / prev_prev)               # last year's price move
            acre_dev = 0.30 * acre_dev + 0.50 * chase + rng.normal(0, 0.02)
            world = 0.5 * world + rng.normal(0, 0.05)
            logp = np.log(k["p"]) - 0.9 * acre_dev - 0.5 * ys.loc[yr] + world
            price = float(np.exp(logp))
            mrows.append(dict(crop=crop, year=yr, acres_planted=round(k["acres"] * 1e6 * np.exp(acre_dev)),
                              price=round(price, 2)))
            prev_prev, prev_price = prev_price, price
    market = pd.DataFrame(mrows)

    # county planted acres follow the market swing (only used for display)
    share = {"wheat": 0.40, "corn": 0.22, "sorghum": 0.18, "soybeans": 0.20}
    dev = market.set_index(["crop", "year"]).acres_planted
    crop_year["acres_planted"] = [
        round(180_000 * share[r.crop] * dev[(r.crop, r.year)] / (P[r.crop]["acres"] * 1e6) * (1 + rng.normal(0, 0.04)))
        for r in crop_year.itertuples()
    ]

    cost = pd.DataFrame([dict(crop=c, year=y, cost_per_acre=round(P[c]["c"] * (1 + 0.008 * (y - START_YEAR))))
                         for c in CROPS for y in years + [END_YEAR + 1]])
    county = pd.DataFrame(COUNTIES, columns=["fips", "name", "lat", "lon"])

    weather.drop(columns=["zsig", "east"]).to_csv(RAW / "weather_season.csv", index=False)
    crop_year[["fips", "crop", "year", "acres_planted", "yield_per_acre"]].to_csv(RAW / "crop_year.csv", index=False)
    market.to_csv(RAW / "market.csv", index=False)
    cost.to_csv(RAW / "cost.csv", index=False)
    county.to_csv(RAW / "county.csv", index=False)
    (RAW / "SOURCE.txt").write_text("sample")
    print(f"Wrote synthetic sample data for {START_YEAR}-{END_YEAR} to {RAW}")


if __name__ == "__main__":
    main()
