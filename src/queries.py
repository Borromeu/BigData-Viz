from pathlib import Path
from typing import Literal

import duckdb

ALLOWED_SOURCES = frozenset({"trips", "sample_trips"})

# Regula 5: Construirea căilor pornind de la locația modulului
SQL_DIR = Path(__file__).resolve().parent / "sql"

# Regula 6: Încărcarea șabloanelor în memorie la import
_HOURS_SQL = (SQL_DIR / "hours.sql").read_text(encoding="utf-8")
_DISTANCE_SQL = (SQL_DIR / "distance.sql").read_text(encoding="utf-8")


def _validate_source(source: str) -> None:
    # Regula 4: Identificatorii dinamici provin exclusiv din opțiuni permise
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"Unknown SQL source {source!r}; allowed: {sorted(ALLOWED_SOURCES)}")


def get_trips_by_hour(conn: duckdb.DuckDBPyConnection, table_name: str):
    _validate_source(table_name)
    query = _HOURS_SQL.replace("{table_name}", table_name)
    return conn.sql(query)


def get_distance_distribution(conn: duckdb.DuckDBPyConnection, table_name: str):
    _validate_source(table_name)
    query = _DISTANCE_SQL.replace("{table_name}", table_name)
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