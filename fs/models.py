"""The three models behind a recommendation.

1. Market cycle  -- how crowded is each crop, and what does that do to the harvest price?
2. Climate fit   -- what yield should this county expect across the weather it actually gets?
3. Margin        -- yield x price - cost, as a range (bad year / typical / good year).

Every function takes a `target` year and only uses data from before it, so the
same code serves the live recommendation and the walk-forward backtest.
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from .config import (ACRE_Z_THRESHOLD, CROPS, PRICE_CHG_THRESHOLD, RISK_AVERSION, TRAIL_YEARS)

PHASE_LABEL = {"BOOM": "Crowded", "BUST": "Under-planted", "NEUTRAL": "Balanced"}
OUTLOOK_WEIGHTS = {"dry": (0.6, 0.3, 0.1), "normal": (1 / 3, 1 / 3, 1 / 3), "wet": (0.1, 0.3, 0.6)}


# --------------------------------------------------------------------------- market cycle

def label_phase(acre_z: float, price_chg_prev: float) -> str:
    """Cobweb rule: lots of acres chasing last year's price jump = BOOM (glut likely)."""
    if acre_z > ACRE_Z_THRESHOLD and price_chg_prev > PRICE_CHG_THRESHOLD:
        return "BOOM"
    if acre_z < -ACRE_Z_THRESHOLD and price_chg_prev < -PRICE_CHG_THRESHOLD:
        return "BUST"
    return "NEUTRAL"


def market_features(market: pd.DataFrame) -> pd.DataFrame:
    """Add acreage anomaly, prior price change and phase to each crop-year."""
    out = []
    for _, g in market.sort_values("year").groupby("crop"):
        g = g.copy()
        prev = g.acres_planted.shift(1)
        base = prev.rolling(TRAIL_YEARS, min_periods=4).mean()
        spread = prev.rolling(TRAIL_YEARS, min_periods=4).std()
        g["acre_anom"] = np.log(g.acres_planted / base)
        g["acre_z"] = (g.acres_planted - base) / spread
        logp = np.log(g.price)
        g["dlogp"] = logp.diff()
        g["dloga"] = np.log(g.acres_planted).diff()
        g["dlogp_prev"] = g.dlogp.shift(1)
        g["acre_anom_prev"] = g.acre_anom.shift(1)
        g["price_chg_prev"] = g.price.pct_change().shift(1)
        g["price_dev"] = logp - logp.shift(1).rolling(TRAIL_YEARS, min_periods=4).mean()
        g["phase"] = [label_phase(z, c) if np.isfinite(z) and np.isfinite(c) else "NEUTRAL"
                      for z, c in zip(g.acre_z, g.price_chg_prev)]
        out.append(g)
    return pd.concat(out, ignore_index=True)


def forecast_market(market: pd.DataFrame, target: int, intentions: dict | None = None) -> pd.DataFrame:
    """Forecast planted acres and harvest price for `target` from data before it.

    Supply response:  dlog(acres_t) = a + b*dlog(price_t-1) + c*acre_anom_t-1
    Price:            log(price_t) - normal log price = a + b*acre_anom_t
    ("normal" = trailing 10-year mean; the same baseline as the acreage anomaly)
    If the fitted area effect has the wrong sign (more area, higher price) it is dropped and the
    price forecast is simply a return to the 10-year normal; `area_effect` reports which applied.
    Both pooled across crops. `intentions` ({crop: acres}) overrides the acreage
    forecast, e.g. with USDA Prospective Plantings.
    """
    feats = market_features(market[market.year < target])
    fit_s = smf.ols("dloga ~ dlogp_prev + acre_anom_prev", feats.dropna(
        subset=["dloga", "dlogp_prev", "acre_anom_prev"])).fit()
    fit_p = smf.ols("price_dev ~ acre_anom", feats.dropna(subset=["price_dev", "acre_anom"])).fit()
    area_effect = bool(fit_p.params["acre_anom"] < 0)
    if not area_effect:
        # More area going with HIGHER prices is demand talking, not crowding. Do not let it drive the
        # forecast: fall back to "price returns to its 10-year normal".
        fit_p = smf.ols("price_dev ~ 1", feats.dropna(subset=["price_dev", "acre_anom"])).fit()
    sigma = float(np.sqrt(fit_p.scale))

    rows = []
    for crop in CROPS:
        g = feats[feats.crop == crop].sort_values("year")
        last = g.iloc[-1]
        base = g.acres_planted.tail(TRAIL_YEARS).mean()
        spread = g.acres_planted.tail(TRAIL_YEARS).std()
        if intentions and crop in intentions:
            acres, acres_src = float(intentions[crop]), "planting intentions"
        else:
            step = fit_s.predict(pd.DataFrame({"dlogp_prev": [last.dlogp], "acre_anom_prev": [last.acre_anom]}))[0]
            acres, acres_src = float(last.acres_planted * np.exp(step)), "supply-response model"
        anom = float(np.log(acres / base))
        normal_logp = float(np.log(g.price.tail(TRAIL_YEARS)).mean())
        dev = fit_p.predict(pd.DataFrame({"acre_anom": [anom]}))[0]
        z = float((acres - base) / spread)
        chg = float(g.price.iloc[-1] / g.price.iloc[-2] - 1)
        rows.append(dict(
            crop=crop, year=target, exp_acres=acres, acres_src=acres_src,
            acres_chg=acres / last.acres_planted - 1, acre_anom=anom, acre_z=z,
            price_chg_prev=chg, phase=label_phase(z, chg),
            last_price=float(last.price), exp_price=float(np.exp(normal_logp + dev)), price_sigma=sigma,
            price_slope=float(fit_p.params.get("acre_anom", 0.0)), area_effect=area_effect))
    return pd.DataFrame(rows).set_index("crop")


# --------------------------------------------------------------------------- climate fit

YIELD_FORMULA = "yield_per_acre ~ C(fips) + year + gs_precip + I(gs_precip ** 2) + heat_days"


def fit_yield_models(crop_year: pd.DataFrame, weather: pd.DataFrame, target: int) -> dict:
    """One regression per crop: county effect + technology trend + rain + heat."""
    panel = crop_year.merge(weather, on=["fips", "year"])
    panel = panel[panel.year < target].dropna(subset=["yield_per_acre", "gs_precip", "heat_days"])
    models = {}
    for crop in CROPS:
        d = panel[panel.crop == crop]
        fit = smf.ols(YIELD_FORMULA, d).fit()
        models[crop] = dict(fit=fit, resid_sd=float(np.sqrt(fit.scale)), fips=set(d.fips), r2=float(fit.rsquared))
    return models


def weather_scenarios(weather: pd.DataFrame, fips: str, target: int, outlook: str = "normal"):
    """Every past season in this county is one possible next season.

    The outlook tilts the odds toward the driest / wettest third of those seasons.
    """
    w = weather[(weather.fips == fips) & (weather.year < target)].copy()
    tercile = pd.qcut(w.gs_precip.rank(method="first"), 3, labels=False)
    weights = np.array(OUTLOOK_WEIGHTS[outlook])[tercile.to_numpy()]
    w["weight"] = weights / weights.sum()
    return w


# --------------------------------------------------------------------------- margin + ranking

class Season:
    """Everything fitted once for a target year; ask it for any county."""

    def __init__(self, tables, target: int, intentions: dict | None = None, n_draws: int = 4000):
        self.t, self.target, self.n = tables, target, n_draws
        self.market = forecast_market(tables.market, target, intentions)
        self.ymodels = fit_yield_models(tables.crop_year, tables.weather, target)
        cost = tables.cost[tables.cost.year <= target].sort_values("year").groupby("crop").cost_per_acre.last()
        self.cost = cost.to_dict()
        self._draws = {}

    def county(self, fips: str, outlook: str = "normal", price_mode: str = "cycle") -> pd.DataFrame:
        """Rank crops for one county.

        price_mode "cycle" uses the crowding-aware price forecast; "naive" assumes
        last year's price simply repeats (the ablation for the backtest).
        """
        wx = weather_scenarios(self.t.weather, fips, self.target, outlook)
        rng = np.random.default_rng(self.target)
        pick = rng.choice(len(wx), size=self.n, p=wx.weight.to_numpy())   # same seasons for every crop
        rows, draws = [], {}
        for crop in CROPS:
            m = self.ymodels[crop]
            if fips not in m["fips"]:
                continue
            X = wx[["gs_precip", "heat_days"]].assign(fips=fips, year=self.target)
            y_by_season = np.clip(m["fit"].predict(X).to_numpy(), 0, None)
            yields = np.clip(y_by_season[pick] + rng.normal(0, m["resid_sd"], self.n), 0, None)
            mk = self.market.loc[crop]
            centre = mk.exp_price if price_mode == "cycle" else mk.last_price
            prices = centre * np.exp(rng.normal(0, mk.price_sigma, self.n))
            margin = yields * prices - self.cost[crop]
            draws[crop] = margin
            p10, p50, p90 = np.percentile(margin, [10, 50, 90])
            dry_yield = float(np.average(y_by_season, weights=(wx.gs_precip <= wx.gs_precip.quantile(1 / 3))))
            rows.append(dict(
                crop=crop, exp_yield=float(np.median(yields)), dry_yield=dry_yield,
                yield_drop_dry=dry_yield / float(np.average(y_by_season)) - 1,
                exp_price=float(centre), last_price=float(mk.last_price), cost=self.cost[crop],
                p10=p10, p50=p50, p90=p90, loss_odds=float((margin < 0).mean()),
                score=p50 - RISK_AVERSION * (p50 - p10),
                phase=mk.phase, acres_chg=float(mk.acres_chg), acre_z=float(mk.acre_z)))
        self._draws[(fips, outlook, price_mode)] = draws
        return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

    def margin_draws(self, fips: str, outlook: str = "normal", price_mode: str = "cycle") -> dict:
        """Simulated one-season margins per crop ({crop: array}). All crops share the same weather draws."""
        key = (fips, outlook, price_mode)
        if key not in self._draws:
            self.county(fips, outlook, price_mode)
        return self._draws[key]


def soil_stress(weather: pd.DataFrame, year: int) -> pd.DataFrame:
    """Spring root-zone soil wetness in `year` as a z-score against each county's own history."""
    hist = weather[weather.year < year].groupby("fips").soil_wet_spring.agg(["mean", "std"])
    now = weather[weather.year == year].set_index("fips")
    out = now[["soil_wet_spring", "gs_precip"]].join(hist)
    out["soil_z"] = (out.soil_wet_spring - out["mean"]) / out["std"]
    return out.reset_index()
