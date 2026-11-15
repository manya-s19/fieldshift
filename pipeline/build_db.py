"""Load the CSVs in data/raw into one DuckDB file the app reads.

Usage:  python pipeline/build_db.py
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fs.config import DB_PATH, RAW  # noqa: E402

TABLES = ["county", "weather_season", "crop_year", "market", "cost"]


def main():
    missing = [t for t in TABLES if not (RAW / f"{t}.csv").exists()]
    if missing:
        sys.exit(f"Missing {missing} in {RAW}. Run make_sample_data.py or the fetch scripts first.")
    DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    for t in TABLES:
        opts = "" if t in ("market", "cost") else ", types={'fips': 'VARCHAR'}"
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{RAW / (t + '.csv')}'{opts})")
        print(f"{t:<15} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>6} rows")
    source = (RAW / "SOURCE.txt").read_text().strip() if (RAW / "SOURCE.txt").exists() else "sample"
    con.execute("CREATE TABLE meta AS SELECT ? AS source", [source])
    con.close()
    print(f"Built {DB_PATH}  (source: {source})")


if __name__ == "__main__":
    main()
