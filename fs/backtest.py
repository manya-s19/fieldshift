"""Walk-forward backtest: for each year, fit on earlier years only, pick a crop
per county under three strategies, then score the pick with what really happened.

  naive      -- plant whatever looked most profitable at last year's price (the cobweb farmer)
  climate    -- Field Shift's weather-risk ranking, but assuming last year's price repeats
  fieldshift -- weather-risk ranking with the crowding-aware price forecast
"""
import numpy as np
import pandas as pd

from .config import CROPS
from .models import Season

STRATEGY_LABEL = {
    "naive": "Chase last year's price",
    "climate": "Climate fit only",
    "fieldshift": "Field Shift (climate + cycle)",
}


def run(tables, first_year: int | None = None, min_history: int = 12) -> pd.DataFrame:
    years = sorted(tables.market.year.unique())
    first_year = first_year or years[0] + min_history
    cy = tables.crop_year.set_index(["fips", "crop", "year"]).yield_per_acre
    price = tables.market.set_index(["crop", "year"]).price
    cost = tables.cost.set_index(["crop", "year"]).cost_per_acre
    wx = tables.weather.copy()
    wx["dry"] = wx.groupby("fips").gs_precip.transform(lambda s: s <= s.quantile(1 / 3))
    dry = wx.set_index(["fips", "year"]).dry

    def realised(fips, crop, yr):
        return cy.get((fips, crop, yr), np.nan) * price[(crop, yr)] - cost[(crop, yr)]

    rows = []
    for yr in [y for y in years if y >= first_year]:
        season = Season(tables, yr, n_draws=1500)
        for fips in tables.county.fips:
            picks = {}
            recent = {c: cy.loc[(fips, c)].loc[yr - 5:yr - 1].mean() for c in CROPS if (fips, c) in cy.index}
            recent = {c: v for c, v in recent.items() if np.isfinite(v)}
            ranked_naive = season.county(fips, price_mode="naive")
            if not recent or ranked_naive.empty:
                continue
            picks["naive"] = max(recent, key=lambda c: recent[c] * price[(c, yr - 1)] - cost[(c, yr - 1)])
            picks["climate"] = ranked_naive.crop.iloc[0]
            picks["fieldshift"] = season.county(fips, price_mode="cycle").crop.iloc[0]
            margins = {s: realised(fips, crop, yr) for s, crop in picks.items()}
            if not all(np.isfinite(m) for m in margins.values()):
                continue          # score a county-year only when every strategy's pick has a real yield
            for strat, crop in picks.items():
                rows.append(dict(year=yr, fips=fips, strategy=strat, crop=crop, margin=margins[strat],
                                 dry=bool(dry.get((fips, yr), False))))
    return pd.DataFrame(rows)


def summarise(bt: pd.DataFrame) -> pd.DataFrame:
    g = bt.groupby("strategy")
    yearly = bt.groupby(["strategy", "year"]).margin.mean()
    out = pd.DataFrame({
        "avg_margin": g.margin.mean(),
        "dry_year_margin": bt[bt.dry].groupby("strategy").margin.mean(),
        "worst_year": yearly.groupby("strategy").min(),
        "loss_share": g.margin.apply(lambda s: (s < 0).mean()),
    })
    return out.reindex(["naive", "climate", "fieldshift"])
