"""Read the tables out of DuckDB."""
from dataclasses import dataclass

import duckdb
import pandas as pd

from .config import DB_PATH


@dataclass
class Tables:
    county: pd.DataFrame
    weather: pd.DataFrame
    crop_year: pd.DataFrame
    market: pd.DataFrame
    cost: pd.DataFrame
    source: str          # "sample" or "real"
    month: pd.DataFrame | None = None   # month-by-month NASA weather (optional)

    @property
    def last_year(self) -> int:
        return int(self.market.year.max())


def load() -> Tables:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "data/fieldshift.duckdb not found. Run:\n"
            "  python pipeline/make_sample_data.py\n  python pipeline/build_db.py")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    q = lambda sql: con.execute(sql).df()  # noqa: E731
    t = Tables(
        county=q("SELECT * FROM county ORDER BY lon"),
        weather=q("SELECT * FROM weather_season ORDER BY fips, year"),
        crop_year=q("SELECT * FROM crop_year ORDER BY fips, crop, year"),
        market=q("SELECT * FROM market ORDER BY crop, year"),
        cost=q("SELECT * FROM cost ORDER BY crop, year"),
        source=q("SELECT source FROM meta").source[0],
    )
    if q("SELECT count(*) AS n FROM information_schema.tables WHERE table_name = 'weather_month'").n[0]:
        t.month = q("SELECT * FROM weather_month ORDER BY fips, year, month")
    con.close()
    return t
