from typing import Literal

import duckdb


ALLOWED_SOURCES = frozenset({"trips", "sample_trips"})
ELIGIBLE_FILTER = """
    pickup_at IS NOT NULL
    AND distance_miles IS NOT NULL
    AND distance_miles > 0
    AND NOT (isnan(distance_miles) OR isinf(distance_miles))
"""


def _validate_source(source: str) -> None:
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"Unknown SQL source {source!r}; allowed: {sorted(ALLOWED_SOURCES)}")


def get_trips_by_hour(conn: duckdb.DuckDBPyConnection, table_name: str):
    _validate_source(table_name)
    query = f"""
        WITH hours AS (SELECT CAST(range AS INTEGER) AS hour FROM range(0, 24)),
        actual_trips AS (
            SELECT EXTRACT(HOUR FROM pickup_at) AS hour, COUNT(*) AS trip_count
            FROM {table_name}
            WHERE {ELIGIBLE_FILTER}
            GROUP BY 1
        )
        SELECT LPAD(CAST(h.hour AS VARCHAR), 2, '0') AS group_key,
               COALESCE(a.trip_count, 0)::BIGINT AS value
        FROM hours h LEFT JOIN actual_trips a ON h.hour = a.hour
        ORDER BY h.hour
    """
    return conn.sql(query)


def get_distance_distribution(conn: duckdb.DuckDBPyConnection, table_name: str):
    _validate_source(table_name)
    query = f"""
        WITH bins AS (SELECT CAST(range AS INTEGER) AS dist_bin FROM range(0, 5)),
        categorized AS (
            SELECT CASE
                WHEN distance_miles > 0 AND distance_miles < 1 THEN 0
                WHEN distance_miles >= 1 AND distance_miles < 2 THEN 1
                WHEN distance_miles >= 2 AND distance_miles < 5 THEN 2
                WHEN distance_miles >= 5 AND distance_miles < 10 THEN 3
                WHEN distance_miles >= 10 THEN 4
                ELSE -1 END AS dist_bin
            FROM {table_name}
            WHERE {ELIGIBLE_FILTER}
        ),
        aggregated AS (
            SELECT dist_bin, COUNT(*) AS trip_count
            FROM categorized WHERE dist_bin >= 0 GROUP BY 1
        )
        SELECT CAST(b.dist_bin AS VARCHAR) AS group_key,
               COALESCE(a.trip_count, 0)::BIGINT AS value
        FROM bins b LEFT JOIN aggregated a USING (dist_bin)
        ORDER BY b.dist_bin
    """
    return conn.sql(query)


def query_counts(conn: duckdb.DuckDBPyConnection,
                 question: Literal["hours", "distance", "trips_by_hour", "distance_distribution"],
                 source: str):
    _validate_source(source)
    if question in ("hours", "trips_by_hour"):
        return get_trips_by_hour(conn, source)
    if question in ("distance", "distance_distribution"):
        return get_distance_distribution(conn, source)
    raise ValueError(f"Unknown question: {question}")
