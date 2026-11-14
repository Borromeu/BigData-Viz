from __future__ import annotations

from pathlib import Path
import time

import duckdb

from src.config import (
    SAMPLING_THREADS,
    validate_sample_rate,
    validate_seed,
)
from src.sampling_core.estimation import estimate_counts

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

ALLOWED_SOURCE_VIEWS = frozenset({"trips"})

_SQL_FILES = {
    "materialize_sample_table": SQL_DIR / "materialize_sample_table.sql",
    "export_sample_parquet": SQL_DIR / "export_sample_parquet.sql",
    "register_sample_parquet": SQL_DIR / "register_sample_parquet.sql",
    "count_parquet_rows": SQL_DIR / "count_parquet_rows.sql",
}


def load_sql_template(template_key: str) -> str:
    if template_key not in _SQL_FILES:
        raise ValueError(f"Unknown SQL template: {template_key!r}")
    return _SQL_FILES[template_key].read_text(encoding="utf-8").strip()


# Încărcăm șabloanele SQL la import (înaintea oricărei măsurători de timp).
_MATERIALIZE_SAMPLE_TABLE_SQL = load_sql_template("materialize_sample_table")
_EXPORT_SAMPLE_PARQUET_SQL = load_sql_template("export_sample_parquet")
_REGISTER_SAMPLE_PARQUET_SQL = load_sql_template("register_sample_parquet")
_COUNT_PARQUET_ROWS_SQL = load_sql_template("count_parquet_rows")


def validate_source_view(source_view: str) -> str:
    if not isinstance(source_view, str) or source_view not in ALLOWED_SOURCE_VIEWS:
        raise ValueError(
            f"Unknown SQL source {source_view!r}; allowed: {sorted(ALLOWED_SOURCE_VIEWS)}"
        )
    return source_view


def validate_output_path(output: str | Path | None) -> Path:
    if output is None or isinstance(output, bool):
        raise ValueError("output path is required.")
    if isinstance(output, str):
        if not output.strip():
            raise ValueError("output path cannot be empty.")
        return Path(output)
    if isinstance(output, Path):
        if not str(output).strip():
            raise ValueError("output path cannot be empty.")
        return output
    raise ValueError("output path must be a str or pathlib.Path.")


def format_bernoulli_sql(template: str, source_view: str, p: float, seed: int) -> str:
    safe_source = validate_source_view(source_view)
    validate_sample_rate(p)
    validate_seed(seed)
    sample_percent = repr(float(p) * 100.0)
    return (
        template.replace("{source_view}", safe_source)
        .replace("{sample_percent}", sample_percent)
        .replace("{seed}", str(int(seed)))
    )


def get_export_sample_sql(source_view: str, p: float, seed: int) -> str:
    return format_bernoulli_sql(_EXPORT_SAMPLE_PARQUET_SQL, source_view, p, seed)


def get_count_parquet_rows_sql() -> str:
    return _COUNT_PARQUET_ROWS_SQL


def get_threads(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT current_setting('threads')").fetchone()
    if row is None:
        raise RuntimeError("Could not read DuckDB threads setting.")
    return int(row[0])


def set_threads(con: duckdb.DuckDBPyConnection, threads: int) -> None:
    con.execute(f"SET threads = {int(threads)}")


def get_memory_limit(con: duckdb.DuckDBPyConnection) -> str:
    row = con.execute("SELECT current_setting('memory_limit')").fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("Could not read DuckDB memory_limit setting.")
    return str(row[0])


def materialize_sample_table(
    con: duckdb.DuckDBPyConnection,
    p: float = 0.10,
    seed: int = 42,
    source_view: str = "trips",
) -> float:
    """Materializează eșantionul Bernoulli într-un tabel temporar sample_trips."""
    sql = format_bernoulli_sql(_MATERIALIZE_SAMPLE_TABLE_SQL, source_view, p, seed)
    previous_threads = get_threads(con)
    set_threads(con, SAMPLING_THREADS)
    start_time = time.perf_counter()
    try:
        con.execute(sql)
    finally:
        elapsed = time.perf_counter() - start_time
        set_threads(con, previous_threads)
    return elapsed


def register_sample_parquet(
    con: duckdb.DuckDBPyConnection,
    sample_path: str | Path,
) -> None:
    """Înregistrează un fișier Parquet deja generat ca vedere sample_trips pentru benchmark."""
    path = validate_output_path(sample_path)
    if not path.exists():
        raise FileNotFoundError(f"Sample Parquet file does not exist: {path}")
    con.execute("SET VARIABLE sample_parquet_path = ?", [str(path.resolve())])
    con.execute(_REGISTER_SAMPLE_PARQUET_SQL)


def sample_and_query(
    con: duckdb.DuckDBPyConnection,
    question: str = "hours",
    sample_rate: float = 0.10,
    seed: int = 42,
    source_view: str = "trips",
) -> list[tuple[str, float]]:
    """Materializează eșantionul, rulează interogarea comună și aplică ponderarea 1/p o dată."""
    from src.queries import query_counts

    materialize_sample_table(con, p=sample_rate, seed=seed, source_view=source_view)
    raw_counts = query_counts(con, question=question, source="sample_trips")
    return estimate_counts(raw_counts, p=sample_rate)
