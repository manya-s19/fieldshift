"""Compare crop rotations on four things a farmer cares about:

  income     -- yearly margin per acre, from the yield / price / cost models
  low risk   -- the same margin in a bad year (1 in 10)
  water      -- how much of the crops' water need is met by NASA-measured rain,
                plus moisture banked during fallow
  soil care  -- a rule-of-thumb score built on the four soil-health principles
                (living roots, diversity, nitrogen from legumes, residue cover)

Reference values used here are general agronomy figures, NOT measurements from
any one field. Each is named below so it can be checked or replaced.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import CROP_LABEL

BARE, COVER = "bare", "cover"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MM_PER_INCH = 25.4

# Seasonal crop water need, mm over the growing period (low, high).
# Source: FAO (1986), Irrigation Water Management: Irrigation Water Needs. Approximate, global.
CROP_WATER_MM = {"corn": (500, 800), "sorghum": (450, 650), "soybeans": (450, 700), "wheat": (450, 650)}

# Share of rain falling on idle ground that is still in the soil for the next crop.
# USDA ARS (Agricultural Research, Jan 2011): fallow loses 65-80% of precipitation to evaporation.
FALLOW_STORAGE = 0.25

HEAVY_RAIN_MM = 25.0          # a "heavy-rain day"

GROUP = {"wheat": "cool-season grass", "corn": "warm-season grass", "sorghum": "warm-season grass",
         "soybeans": "legume", COVER: "cover-crop mix"}
HEAVY_RESIDUE = {"wheat", "corn", "sorghum", COVER}      # soybeans leave little residue
LEGUME = {"soybeans", COVER}                              # the cover crop is assumed to be a mix with a legume
PHASE_LABEL = {**CROP_LABEL, BARE: "Nothing growing", COVER: "Cover crop"}
PHASE_SHORT = {"wheat": "Wheat", "corn": "Corn", "sorghum": "Sorghum", "soybeans": "Soybeans",
               BARE: "", COVER: "Cover"}


@dataclass(frozen=True)
class Rotation:
    id: str
    name: str
    start_month: int                 # calendar month (1-12) the first phase starts
    phases: tuple                    # ((kind, months), ...) kind = crop, "bare" or "cover"
    benefits: tuple
    risks: tuple

    @property
    def months(self) -> int:
        return sum(n for _, n in self.phases)

    @property
    def years(self) -> int:
        return self.months // 12

    @property
    def crops(self) -> list:
        return [k for k, _ in self.phases if k not in (BARE, COVER)]

    @property
    def has_cover(self) -> bool:
        return any(k == COVER for k, _ in self.phases)

    @property
    def bare_months(self) -> int:
        return sum(n for k, n in self.phases if k == BARE)

    @property
    def bare_per_year(self) -> float:
        return self.bare_months / self.years


ROTATIONS = [
    Rotation("wf", "Wheat, then fallow", 10, (("wheat", 9), (BARE, 15)),
             benefits=("The fallow year banks moisture, so the wheat crop is steadier in dry country.",
                       "Simple to run: one crop and one set of equipment."),
             risks=("The field has nothing growing for 15 months out of 24. Without good stubble cover that "
                    "ground is open to wind and water erosion.",
                    "Most of the rain that falls during fallow evaporates before a crop can use it.",
                    "With only one crop, grassy weeds and wheat diseases tend to build up.")),
    Rotation("ww", "Wheat every year", 10, (("wheat", 9), (BARE, 3)),
             benefits=("Something is growing nine months of every year.",
                       "Simple to run, and a harvest every year."),
             risks=("No break crop: wheat diseases and grassy weeds build up year after year.",
                    "Only a short summer gap to bank moisture, so a dry autumn hits the next crop directly.",
                    "All income rides on one crop and one price.")),
    Rotation("wsf", "Wheat, sorghum, then fallow", 10,
             (("wheat", 9), (BARE, 11), ("sorghum", 5), (BARE, 11)),
             benefits=("Two harvests in three years where wheat-fallow gives one in two.",
                       "Sorghum copes with heat and dry spells better than corn.",
                       "Alternating a winter crop with a summer crop helps break weed and disease cycles."),
             risks=("Sorghum relies on moisture banked over winter. A dry winter and spring can leave it short.",
                    "Still two long idle stretches, so stubble cover matters.",
                    "Check herbicide carry-over between wheat and sorghum with your agronomist.")),
    Rotation("wcf", "Wheat, corn, then fallow", 10,
             (("wheat", 9), (BARE, 10), ("corn", 5), (BARE, 12)),
             benefits=("Two harvests in three years where wheat-fallow gives one in two.",
                       "Corn pays well in years with good summer rain.",
                       "Alternating a winter crop with a summer crop helps break weed and disease cycles."),
             risks=("Corn is the thirstiest crop here and is hit hardest by heat at tasselling.",
                    "Higher seed and fertiliser bills mean more money at risk in a dry year.",
                    "Still two long idle stretches, so stubble cover matters.")),
    Rotation("wsf_cover", "Wheat, cover crop, sorghum, then fallow", 10,
             (("wheat", 9), (COVER, 3), (BARE, 8), ("sorghum", 5), (BARE, 11)),
             benefits=("A cover crop after wheat harvest keeps living roots in the soil and shields it "
                       "from summer storms.",
                       "A mix that includes a legume adds nitrogen for the next crop.",
                       "The cover crop can be grazed or cut for hay (that income is not counted here)."),
             risks=("In dry country a cover crop uses moisture the next crop would have had. Field trials on the "
                    "High Plains have often found lower yields in the crop that follows.",
                    "Seed and planting cost money with nothing to sell unless it is grazed.",
                    "Choose species and a kill date with local advice: both change how much water is used.")),
    Rotation("wssb", "Wheat, sorghum, then soybeans", 10,
             (("wheat", 9), (BARE, 11), ("sorghum", 5), (BARE, 7), ("soybeans", 4)),
             benefits=("Soybeans are a legume: they fix nitrogen from the air.",
                       "Three different kinds of crop (a winter grass, a summer grass and a legume) break "
                       "pest and disease cycles.",
                       "A harvest every year, with no fallow year."),
             risks=("No fallow year means little banked moisture. That is riskier where rain is short.",
                    "Soybeans leave little residue, so the ground is more exposed after them.",
                    "Wheat has to go in straight after soybean harvest. That window is tight.")),
    Rotation("cs", "Corn, then soybeans", 5,
             (("corn", 5), (BARE, 8), ("soybeans", 5), (BARE, 6)),
             benefits=("Soybeans fix nitrogen that the following corn can use.",
                       "Both crops have deep, well-known markets.",
                       "A harvest every year."),
             risks=("Both are summer crops, so the same July and August heat or drought hits both.",
                    "The field has nothing growing all winter after each crop.",
                    "Soybeans leave little residue, so the ground is more exposed after them.")),
    Rotation("csw_cover", "Corn, soybeans, wheat, then a cover crop", 5,
             (("corn", 5), (BARE, 8), ("soybeans", 4), ("wheat", 9), (COVER, 4), (BARE, 6)),
             benefits=("Three kinds of crop plus a cover crop: the most variety of any option here.",
                       "Winter wheat spreads weather risk across two seasons.",
                       "The cover crop after wheat keeps living roots in the soil and protects it "
                       "through autumn."),
             risks=("More crops mean more equipment, more timing to get right and more to market.",
                    "Wheat has to go in straight after soybean harvest. That window is tight.",
                    "The cover crop costs money with nothing to sell unless it is grazed.")),
]
BY_ID = {r.id: r for r in ROTATIONS}

COMMON_GAPS = (
    "Yields are county averages scaled to dryland. Your fields, soil type and irrigation are not in here.",
    "The model does not know that a crop often yields differently depending on what came before it.",
    "Tillage is not scored. No-till keeps far more residue and moisture than worked ground.",
    "Crop water needs are general FAO reference ranges, not figures for local varieties.",
    "NASA rain figures are area averages on a grid about 50 km wide. They smooth out the heaviest "
    "local storms, so a rain gauge on your farm is the better record.",
    "Soil type, slope and existing erosion are not included yet.",
)


# --------------------------------------------------------------------------- timeline

def timeline(rot: Rotation) -> list:
    """[(kind, first calendar month 1-12, months), ...] in order."""
    out, m = [], rot.start_month
    for kind, n in rot.phases:
        out.append((kind, m, n))
        m = (m - 1 + n) % 12 + 1
    return out


def sequence_text(rot: Rotation) -> str:
    parts = []
    for kind, m, n in timeline(rot):
        end = MONTHS[(m - 1 + n - 1) % 12]
        if kind == BARE:
            parts.append(f"nothing growing {n} months")
        else:
            parts.append(f"{PHASE_LABEL[kind].lower()} {MONTHS[m - 1]}-{end}")
    return ", then ".join(parts)


# --------------------------------------------------------------------------- soil care

def soil_score(rot: Rotation) -> dict:
    """Four parts, 0-100 each, averaged. A rule of thumb, not a soil test."""
    grown = [k for k, _ in rot.phases if k != BARE]
    roots = 100 * (1 - rot.bare_months / rot.months)
    variety = 100 * min(len({GROUP[k] for k in grown}), 4) / 4
    nitrogen = 100.0 if any(k in LEGUME for k in grown) else 0.0
    residue = 100 * np.mean([k in HEAVY_RESIDUE for k in grown])
    return dict(soil=float(np.mean([roots, variety, nitrogen, residue])), soil_roots=float(roots),
                soil_variety=float(variety), soil_nitrogen=nitrogen, soil_residue=float(residue),
                groups=sorted({GROUP[k] for k in grown}))


# --------------------------------------------------------------------------- water

def month_tables(month_df: pd.DataFrame, fips: str):
    """Rain and heavy-rain days as year x month tables for one county."""
    d = month_df[month_df.fips == fips]
    rain = d.pivot(index="year", columns="month", values="precip")
    heavy = d.pivot(index="year", columns="month", values="heavy_days") if "heavy_days" in d else None
    return rain, heavy


def water_balance(rot: Rotation, rain: pd.DataFrame, heavy: pd.DataFrame | None) -> dict:
    """Replay the rotation from every possible start year in the NASA record.

    A crop's supply = rain while it is in the ground + FALLOW_STORAGE x rain on the idle months
    before it. A cover crop is assumed to use the rain that falls on it, banking none.
    Two cycles are run and the second is scored, so the first crop starts with a realistic bank.
    """
    need = {c: float(np.mean(CROP_WATER_MM[c])) for c in rot.crops}
    rows = []
    for y0 in rain.index:
        seq, y, m = [], int(y0), rot.start_month
        for _ in range(2 * rot.months):
            seq.append((y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        if seq[-1][0] > rain.index.max():
            break
        r = np.array([rain.at[yy, mm] if (yy in rain.index and mm in rain.columns) else np.nan for yy, mm in seq])
        if np.isnan(r).any():
            continue
        h = None if heavy is None else np.array([heavy.at[yy, mm] for yy, mm in seq], dtype=float)
        bank, t, need_tot, met_tot, bare_rain, bare_heavy = 0.0, 0, 0.0, 0.0, 0.0, 0.0
        for cycle in (0, 1):
            for kind, n in rot.phases:
                rr = float(r[t:t + n].sum())
                if kind == BARE:
                    bank += FALLOW_STORAGE * rr
                    if cycle:
                        bare_rain += rr
                        bare_heavy += 0.0 if h is None else float(np.nansum(h[t:t + n]))
                elif kind == COVER:
                    bank = 0.0
                else:
                    if cycle:
                        need_tot += need[kind]
                        met_tot += min(need[kind], rr + bank)
                    bank = 0.0
                t += n
        rows.append((int(y0), met_tot / need_tot, bare_rain / rot.years, bare_heavy / rot.years))
    if not rows:
        return {}
    a = np.array(rows)
    return dict(water_typ=float(np.median(a[:, 1])), water_dry=float(np.percentile(a[:, 1], 20)),
                water_need=sum(need.values()) / rot.years,
                bare_rain=float(np.median(a[:, 2])),
                bare_heavy=None if heavy is None else float(a[:, 3].mean()),
                water_cycles=len(rows), water_from=int(a[:, 0].min()), water_to=int(rain.index.max()))


# --------------------------------------------------------------------------- money

def yearly_margin(rot: Rotation, draws: dict, idle_cost: float, cover_cost: float) -> np.ndarray:
    """Margin per acre per year, for a farm with one field in each stage of the rotation.

    draws[crop] are simulated one-season margins that share the same weather, so a hot dry
    year hits every summer crop together.
    """
    total = sum(draws[c] for c in rot.crops)
    total = total - idle_cost * rot.bare_months / 12 - cover_cost * sum(k == COVER for k, _ in rot.phases)
    return total / rot.years


# --------------------------------------------------------------------------- evaluate + rank

def evaluate(season, tables, fips: str, outlook: str = "normal", idle_cost: float = 30.0,
             cover_cost: float = 35.0) -> pd.DataFrame:
    """One row per rotation that can be grown in this county."""
    draws = season.margin_draws(fips, outlook)
    month_df = getattr(tables, "month", None)
    rain = heavy = None
    if month_df is not None and len(month_df):
        rain, heavy = month_tables(month_df, fips)
    rows = []
    for rot in ROTATIONS:
        if any(c not in draws for c in rot.crops):
            continue
        m = yearly_margin(rot, draws, idle_cost, cover_cost)
        p10, p50, p90 = np.percentile(m, [10, 50, 90])
        row = dict(id=rot.id, name=rot.name, years=rot.years, p10=p10, p50=p50, p90=p90,
                   loss_odds=float((m < 0).mean()), bare_per_year=rot.bare_per_year,
                   water_typ=np.nan, water_dry=np.nan, water_need=np.nan, bare_rain=np.nan, bare_heavy=np.nan)
        row.update(soil_score(rot))
        if rain is not None:
            row.update(water_balance(rot, rain, heavy))
        rows.append(row)
    return pd.DataFrame(rows).set_index("id", drop=False)


DIMENSIONS = {"income": "p50", "risk": "p10", "water": "water_dry", "soil": "soil"}


def rank(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """Score each rotation 0-100 on every priority (relative to the other options) and blend."""
    out = df.copy()
    w = {k: float(weights.get(k, 0)) for k in DIMENSIONS}
    if out.water_dry.isna().all():
        w["water"] = 0.0                       # no month-by-month rain loaded
    if sum(w.values()) == 0:
        w = {k: 1.0 for k in w}
        if out.water_dry.isna().all():
            w["water"] = 0.0
    fit = 0
    for dim, col in DIMENSIONS.items():
        v = out[col].astype(float)
        span = v.max() - v.min()
        out[f"s_{dim}"] = 50.0 if not span > 0 else 100 * (v - v.min()) / span
        fit = fit + w[dim] * out[f"s_{dim}"].fillna(0)
    out["fit"] = fit / sum(w.values())
    return out.sort_values("fit", ascending=False)


# --------------------------------------------------------------------------- words

def money(x: float) -> str:
    x = round(x)
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def inches(mm: float) -> str:
    return f"{mm / MM_PER_INCH:.1f} in"


def why(row, cur, weights: dict) -> str:
    """One or two plain sentences: what this rotation gains and gives up against the current one."""
    if row.id == cur.id:
        return "This is what you grow now. It is the yardstick for the other two."
    gains, costs = [], []

    def note(better, text_up, text_down, big):
        if big:
            (gains if better else costs).append(text_up if better else text_down)

    d = row.p50 - cur.p50
    note(d > 0, f"earns about {money(abs(d))} more per acre a year", f"earns about {money(abs(d))} less per acre a year",
         abs(d) >= 5)
    d = row.p10 - cur.p10
    note(d > 0, f"holds up better in a bad year (by about {money(abs(d))} an acre)",
         f"does worse in a bad year (by about {money(abs(d))} an acre)", abs(d) >= 5)
    if pd.notna(row.water_dry) and pd.notna(cur.water_dry):
        d = row.water_dry - cur.water_dry
        note(d > 0, "has more of its water need met by rain in dry years",
             "has less of its water need met by rain in dry years", abs(d) >= 0.03)
    d = row.soil - cur.soil
    note(d > 0, "does more for the soil", "does less for the soil", abs(d) >= 5)
    d = cur.bare_per_year - row.bare_per_year
    note(d > 0, f"leaves the field idle {abs(d):.1f} fewer months a year",
         f"leaves the field idle {abs(d):.1f} more months a year", abs(d) >= 0.5)

    def join(xs):
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]

    if not gains and not costs:
        return "On these measures it comes out about the same as what you grow now."
    text = f"Against what you grow now, it {join(gains)}." if gains else "It does not beat what you grow now on any measure here."
    if costs:
        text += f" The trade-off: it {join(costs)}."
    return text


def evidence(row, rot: Rotation, county: str) -> list:
    out = [f"Income: USDA county yields (scaled to dryland), long-run normal prices and USDA cost figures give "
           f"about {money(row.p50)} an acre a year in a normal year, {money(row.p10)} in a bad year "
           f"(1 in 10) and {money(row.p90)} in a good one."]
    if pd.notna(row.water_dry):
        out.append(f"Water: the crops need about {inches(row.water_need)} of water a year. Across "
                   f"{int(row.water_cycles)} replays of NASA rain records for {county} County "
                   f"({int(row.water_from)}-{int(row.water_to)}), rain plus banked fallow moisture met "
                   f"{row.water_typ:.0%} of that in a typical run and {row.water_dry:.0%} in a dry one (1 in 5).")
        heavy = "" if row.bare_heavy is None or pd.isna(row.bare_heavy) else \
            f", including about {row.bare_heavy:.1f} heavy-rain days"
        out.append(f"Idle ground: nothing is growing for {row.bare_per_year:.1f} months of an average year. "
                   f"About {inches(row.bare_rain)} of rain a year falls in those months{heavy}.")
    else:
        out.append(f"Idle ground: nothing is growing for {row.bare_per_year:.1f} months of an average year. "
                   "Month-by-month NASA rain is not loaded yet, so water figures are missing.")
    out.append(f"Soil care {row.soil:.0f}/100: living roots {row.soil_roots:.0f}, crop variety "
               f"{row.soil_variety:.0f}, nitrogen from legumes {row.soil_nitrogen:.0f}, residue left "
               f"behind {row.soil_residue:.0f}.")
    return out


def sms_text(county: str, cur, best) -> str:
    """Text alert comparing the current rotation with the best fit. Two SMS segments at most."""
    if best.id == cur.id:
        return (f"FIELD SHIFT {county} Co.: your rotation ({cur['name'].lower()}) already fits your priorities "
                f"best: about {money(cur.p50)}/ac a yr, {money(cur.p10)} in a bad yr. Reply MORE for options.")
    water = "" if pd.isna(best.water_dry) else f" Rain meets {best.water_dry:.0%} of crop water need in dry yrs."
    return (f"FIELD SHIFT {county} Co.: you now earn about {money(cur.p50)}/ac a yr. Worth a look: "
            f"{best['name'].lower()}, about {money(best.p50)}/ac ({money(best.p10)} in a bad yr).{water} "
            f"Check with your agronomist. Reply MORE.")
