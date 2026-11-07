from pathlib import Path
from typing import Literal

import duckdb

ALLOWED_SOURCES = frozenset({"trips", "sample_trips"})
ELIGIBLE_FILTER = """
    pickup_at IS NOT NULL
    AND distance_miles IS NOT NULL
    AND distance_miles > 0
    AND NOT (isnan(distance_miles) OR isinf(distance_miles))
"""

SQL_DIR = Path(__file__).resolve().parent / "sql"


def _read_sql_template(filename: str) -> str:
    path = SQL_DIR / filename
    return path.read_text(encoding="utf-8")


HOURS_SQL_TEMPLATE = _read_sql_template("hours.sql")
DISTANCE_SQL_TEMPLATE = _read_sql_template("distance.sql")


def _validate_source(source: str) -> None:
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"Unknown SQL source {source!r}; allowed: {sorted(ALLOWED_SOURCES)}")


def get_trips_by_hour(conn: duckdb.DuckDBPyConnection, table_name: str):
    _validate_source(table_name)
    query = HOURS_SQL_TEMPLATE.format(table_name=table_name, ELIGIBLE_FILTER=ELIGIBLE_FILTER)
    return conn.sql(query)


def get_distance_distribution(conn: duckdb.DuckDBPyConnection, table_name: str):
    _validate_source(table_name)
    query = DISTANCE_SQL_TEMPLATE.format(table_name=table_name, ELIGIBLE_FILTER=ELIGIBLE_FILTER)
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