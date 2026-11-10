from pathlib import Path

import duckdb

from src.plots import plot_distance_distribution
from src.queries import query_counts
from src.sampling import estimate_counts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "trips.csv"
OUTPUT = PROJECT_ROOT / "results" / "distance_distribution_demo.html"
ANALYSIS_PERIOD = "[2025-01-01, 2025-02-01)"
RANDOM_SEED = 42
SAMPLE_RATES = (1 / 3, 2 / 3)


def main():
    con = duckdb.connect()
    try:
        con.execute(f"""
            CREATE TABLE trips AS
            SELECT tpep_pickup_datetime AS pickup_at,
                   trip_distance AS distance_miles,
                   PULocationID AS pickup_zone, fixture_id
            FROM read_csv_auto('{FIXTURE.as_posix()}')
            WHERE fixture_id BETWEEN 1 AND 12
        """)
        exact = query_counts(con, "distance", "trips").df()
        sample_options = {}
        for rate in SAMPLE_RATES:
            threshold = round(rate * 3)
            con.execute("DROP TABLE IF EXISTS sample_trips")
            con.execute(f"""
                CREATE TABLE sample_trips AS SELECT * FROM trips
                WHERE hash(fixture_id + {RANDOM_SEED}) % 3 < {threshold}
            """)
            raw = query_counts(con, "distance", "sample_trips").df()
            sample_options[rate] = estimate_counts(raw, rate)

        default_rate = SAMPLE_RATES[0]
        sample = sample_options[default_rate]
        empty = sample.value.sum() == 0
        fig = plot_distance_distribution(
            exact, sample, default_rate, status="empty_sample" if empty else "ok",
            analysis_period=ANALYSIS_PERIOD, random_seed=RANDOM_SEED,
            sample_options=sample_options,
        )
    finally:
        con.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUTPUT, include_plotlyjs=True, full_html=True)
    return OUTPUT


if __name__ == "__main__":
    print(main())
