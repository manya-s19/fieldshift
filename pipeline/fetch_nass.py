"""Pull real crop data from the USDA NASS QuickStats API.

Needs a free key: https://quickstats.nass.usda.gov/api  ->  export NASS_API_KEY=...

Output:
  data/raw/crop_year.csv   county planted acres + dryland-basis yield (Kansas)
  data/raw/market.csv      US planted acres + Kansas marketing-year price
  data/raw/SOURCE.txt      set to "real"

Market acreage is taken at the US level on purpose: grain prices are set by the
whole market, so "is everyone piling in?" has to be measured there.

Costs are not in QuickStats. Edit data/raw/cost.csv by hand from the USDA ERS
"Commodity Costs and Returns" tables (crop, year, cost_per_acre).

Usage:  python pipeline/fetch_nass.py
"""
import os
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fs.config import COUNTIES, RAW, START_YEAR, STATE  # noqa: E402

URL = "https://quickstats.nass.usda.gov/api/api_GET/"

# crop -> (acres item, yield item, price item, price multiplier to $/bu)
ITEMS = {
    "wheat": ("WHEAT, WINTER - ACRES PLANTED",
              "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE",
              "WHEAT, WINTER - PRICE RECEIVED, MEASURED IN $ / BU", 1.0),
    "corn": ("CORN - ACRES PLANTED",
             "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE",
             "CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU", 1.0),
    "sorghum": ("SORGHUM - ACRES PLANTED",
                "SORGHUM, GRAIN - YIELD, MEASURED IN BU / ACRE",
                "SORGHUM, GRAIN - PRICE RECEIVED, MEASURED IN $ / CWT", 0.56),  # 56 lb per bushel
    "soybeans": ("SOYBEANS - ACRES PLANTED",
                 "SOYBEANS - YIELD, MEASURED IN BU / ACRE",
                 "SOYBEANS - PRICE RECEIVED, MEASURED IN $ / BU", 1.0),
}


def dryland_basis(cy: pd.DataFrame) -> pd.DataFrame:
    """Put every crop on a dryland footing.

    USDA publishes dryland county yields only for some years (mostly 2000-2009), so they cannot be
    used directly. Instead, for each county and crop, take the typical ratio of dryland yield to
    all-fields yield in the years that have both, and apply it to the full all-fields history:
        yield_per_acre = yield_all_fields x dryland_ratio
    A county with no overlapping year borrows the crop's median ratio across counties.
    A ratio near 1 means the crop is grown dryland there anyway; near 0.3 means mostly irrigated.
    """
    cy = cy.copy()
    ratio = (cy.yield_dryland / cy.yield_all_fields).clip(upper=1.0)
    by_county = ratio.groupby([cy.fips, cy.crop]).agg(["median", "count"])
    crop_median = by_county[by_county["count"] >= 1].groupby("crop")["median"].median()
    def pick(row):
        m, n = by_county.loc[(row.fips, row.crop)]
        return m if n >= 1 else crop_median.get(row.crop, 1.0)
    cy["dryland_ratio"] = cy.apply(pick, axis=1).round(3)
    cy["yield_per_acre"] = (cy.yield_all_fields * cy.dryland_ratio).round(1)
    cols = ["fips", "crop", "year", "acres_planted", "yield_per_acre", "yield_all_fields", "dryland_ratio"]
    return cy[[c for c in cols if c in cy]]


def query(key, **params):
    r = requests.get(URL, timeout=120, params=dict(
        key=key, source_desc="SURVEY", year__GE=START_YEAR, format="JSON", **params))
    if r.status_code != 200:
        print(f"  !! HTTP {r.status_code} for {params.get('short_desc')}: {r.text[:200]}")
        return pd.DataFrame()
    df = pd.DataFrame(r.json().get("data", []))
    if df.empty:
        print(f"  !! no rows for {params.get('short_desc')} -- check the item name in QuickStats")
        return df
    df["value"] = pd.to_numeric(df["Value"].str.replace(",", ""), errors="coerce")  # "(D)" -> NaN
    df["year"] = df["year"].astype(int)
    return df.dropna(subset=["value"])


def main():
    key = os.environ.get("NASS_API_KEY")
    if not key:
        sys.exit("Set NASS_API_KEY first (free: https://quickstats.nass.usda.gov/api)")
    wanted = {c[0] for c in COUNTIES}
    county_frames, market_rows = [], []

    for crop, (acres_item, yield_item, price_item, mult) in ITEMS.items():
        print(f"NASS  {crop}")
        parts = {}
        for col, item in (("acres_planted", acres_item), ("yield_per_acre", yield_item)):
            df = query(key, short_desc=item, agg_level_desc="COUNTY", state_alpha=STATE)
            if df.empty:
                continue
            df["fips"] = df["state_fips_code"] + df["county_code"]
            df = df[df.fips.isin(wanted) & (df.reference_period_desc == "YEAR")]
            parts[col] = df.groupby(["fips", "year"]).value.first().rename(col)
            print(f"  county {col}: {len(parts[col])} rows")
        # Dryland (non-irrigated) yields exist only for some years; keep them next to the all-fields
        # series so dryland_basis() can put every crop on the same footing.
        dry = query(key, short_desc=yield_item.replace(" - YIELD", ", NON-IRRIGATED - YIELD"),
                    agg_level_desc="COUNTY", state_alpha=STATE)
        if not dry.empty and "yield_per_acre" in parts:
            dry["fips"] = dry["state_fips_code"] + dry["county_code"]
            dry = dry[dry.fips.isin(wanted) & (dry.reference_period_desc == "YEAR")]
            parts["yield_dryland"] = dry.groupby(["fips", "year"]).value.first().rename("yield_dryland")
            print(f"  county dryland yield: {len(parts['yield_dryland'])} rows")
        if parts:
            cy = pd.concat(parts.values(), axis=1).reset_index()
            cy.insert(1, "crop", crop)
            county_frames.append(cy)

        us = query(key, short_desc=acres_item, agg_level_desc="NATIONAL")
        pr = query(key, short_desc=price_item, agg_level_desc="STATE", state_alpha=STATE,
                   reference_period_desc="MARKETING YEAR")
        if us.empty or pr.empty:
            continue
        us = us[us.reference_period_desc == "YEAR"].groupby("year").value.first()
        pr = pr.groupby("year").value.first() * mult
        both = pd.concat([us.rename("acres_planted"), pr.rename("price")], axis=1).dropna().reset_index()
        both.insert(0, "crop", crop)
        market_rows.append(both)
        print(f"  market: {len(both)} years")

    if not county_frames or not market_rows:
        sys.exit("Nothing downloaded -- sample data left untouched.")
    RAW.mkdir(parents=True, exist_ok=True)
    cy = pd.concat(county_frames).rename(columns={"yield_per_acre": "yield_all_fields"})
    if "yield_dryland" not in cy:
        cy["yield_dryland"] = float("nan")
    cy = dryland_basis(cy.dropna(subset=["yield_all_fields"]))
    cy.to_csv(RAW / "crop_year.csv", index=False)
    ratios = cy.groupby(["fips", "crop"]).dryland_ratio.first().unstack().round(2)
    print("Dryland share of the all-fields yield, by county and crop:")
    print(ratios.to_string())
    pd.concat(market_rows).round({"price": 2}).to_csv(RAW / "market.csv", index=False)
    (RAW / "SOURCE.txt").write_text("real")
    print("Done. Now run fetch_power.py (if you have not), check cost.csv, then build_db.py")


if __name__ == "__main__":
    main()
