# Field Shift

A web dashboard plus a text-alert channel that tells a farmer what to plant next season, using two signals:

1. **Climate fit**: how each crop yields in this county across the weather it actually gets (NASA POWER).
2. **Market cycle**: whether everyone else is about to plant the same thing, and what that does to the harvest price (USDA).

The main view, **My rotation**, answers the challenge brief: a farmer picks what they grow now and sees it beside the two rotations that best fit their priorities (income, getting through a bad year, saving water, looking after the soil). Each option shows its evidence, benefits, information gaps and risks to check locally.

MVP scope: Kansas, 14 counties, four crops (winter wheat, corn, sorghum, soybeans), eight rotations.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The zip ships with **simulated sample data** so the app opens straight away. The banner at the top of the app says so until real data is loaded.

## Switch to real data

```bash
python pipeline/fetch_power.py                 # NASA POWER, no key
export NASS_API_KEY=your_key                   # free: https://quickstats.nass.usda.gov/api
python pipeline/fetch_nass.py                  # USDA NASS QuickStats
# edit data/raw/cost.csv with USDA ERS cost-per-acre figures
python pipeline/build_db.py
streamlit run app.py
```

The two fetch scripts were written against the API documentation but have **not been run against the live services** (the build environment had no access to them). Each prints row counts per query, so an item name that returns nothing is easy to spot and fix in `ITEMS` at the top of `fetch_nass.py`.

`cost.csv` holds placeholder costs. Replace them before trusting any margin.

## What is where

| Path | What it does |
|---|---|
| `app.py` | The dashboard: recommendation, market cycles, regional stress, backtest |
| `fs/rotations.py` | The eight rotations, water balance, soil-care score, ranking and the plain-language explanations |
| `fs/models.py` | Cobweb phase labeller, supply-response and price models, yield model, margin simulation, ranking |
| `fs/backtest.py` | Walk-forward backtest against two baselines |
| `fs/alerts.py` | Builds the SMS text; `send_sms` is the stub to wire to Twilio |
| `fs/config.py` | Counties, crops, thresholds |
| `pipeline/` | Sample-data generator, real-data fetchers, DuckDB builder |

## How rotations are compared

- **Income / bad year**: the single-season margins below, summed over the crops in the rotation with shared weather, divided by years in the cycle. Idle-ground and cover-crop costs are entered in the sidebar (the defaults are guesses).
- **Water**: the rotation is replayed through NASA POWER monthly rain from every start year. Supply = rain while the crop is in the ground + 25% of rain on the idle months before it (USDA ARS: fallow loses 65-80% to evaporation). Need = midpoint of the FAO (1986) range per crop.
- **Soil care**: average of living-root months, crop variety, legume present, heavy-residue crops. A rule of thumb, not a soil test.
- **Months idle**: from typical Kansas planting and harvest months in `fs/rotations.py`.

Month-by-month rain comes from `pipeline/fetch_power.py` (`data/raw/weather_month.csv`). Until that file is built into the database, water figures show as n/a.

## How a recommendation is made

- **Dryland footing**: USDA publishes dryland county yields only for some years, so `fetch_nass.py` scales each all-fields yield by the county and crop's typical dryland share (`dryland_ratio` in `crop_year.csv`). This assumes that share is stable over time.
- **Yield**: per crop, `yield ~ county + year + rain + rain² + heat days`. Every past season in the county is replayed as a possible next season; the outlook control tilts the odds toward dry or wet ones.
- **Planted area**: `Δlog(area) ~ Δlog(last year's price) + last year's area anomaly`. Override it in the sidebar with USDA Prospective Plantings.
- **Price**: `log(price) − 10-year normal ~ area anomaly`. More area than normal means a lower expected price.
- **Phase**: crowded if area z-score > 0.75 after a price rise > 10%; under-planted in the mirror case.
- **Rank**: typical margin minus half the gap down to a bad (1-in-10) year.

## Backtest

For each year the models are refitted on earlier years only, one crop is picked per county, and the pick is scored with what actually happened. Baselines: chasing last year's price, and Field Shift with the cycle signal switched off.

On the sample data the result is meaningless as evidence, because the simulation contains a cobweb by construction. Quote it only after loading real data, and report it whichever way it comes out.

## Deploy

Push to GitHub and point Streamlit Community Cloud at `app.py`. Commit `data/fieldshift.duckdb` so the hosted app has data.

## Known limits

- Prices are state-level; costs are regional.
- The backtest scores only county-seasons where USDA published a yield for every strategy's pick, about half of them.
- The crowding signal is a forecast, not a measurement. MODIS NDVI or Prospective Plantings would firm it up in season.
- Winter wheat is sown the autumn before, so its ranking applies to next autumn's decision.
- Rotations, irrigation and crop insurance are not modelled.
