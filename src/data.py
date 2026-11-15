from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import duckdb


def register_trips(
    con: duckdb.DuckDBPyConnection,
    files: Sequence[str | Path],
    start: datetime,
    end: datetime,
) -> None:
    """Înregistrează vederea trips conform contractului comun al proiectului.

    Populația filtrată comună:
      - pickup_at: timestamp nenul în [start, end)
      - distance_miles: distanță finită și strict pozitivă (> 0)
      - pickup_zone: zonă normalizată (NULL -> 0)
    """
    if not files:
        raise ValueError("files list cannot be empty.")

    resolved_paths = [str(Path(f).resolve().as_posix()) for f in files]
    for p in resolved_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"Source file not found: {p}")

    start_str = start.isoformat(sep=" ")
    end_str = end.isoformat(sep=" ")

    con.execute("SET VARIABLE data_start_ts = ?", [start_str])
    con.execute("SET VARIABLE data_end_ts = ?", [end_str])

    file_literals = ", ".join(f"'{p}'" for p in resolved_paths)
    if any(str(p).lower().endswith(".csv") for p in resolved_paths):
        read_expr = f"read_csv_auto([{file_literals}])"
    else:
        read_expr = f"read_parquet([{file_literals}])"

    con.execute(
        f"""
        CREATE OR REPLACE VIEW trips AS
        SELECT
            CAST(tpep_pickup_datetime AS TIMESTAMP) AS pickup_at,
            CAST(trip_distance AS DOUBLE) AS distance_miles,
            COALESCE(CAST(PULocationID AS INTEGER), 0) AS pickup_zone
        FROM {read_expr}
        WHERE tpep_pickup_datetime IS NOT NULL
          AND CAST(tpep_pickup_datetime AS TIMESTAMP) >= CAST(getvariable('data_start_ts') AS TIMESTAMP)
          AND CAST(tpep_pickup_datetime AS TIMESTAMP) < CAST(getvariable('data_end_ts') AS TIMESTAMP)
          AND trip_distance IS NOT NULL
          AND isfinite(CAST(trip_distance AS DOUBLE))
          AND CAST(trip_distance AS DOUBLE) > 0
        """
    )
