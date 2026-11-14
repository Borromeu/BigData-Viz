from __future__ import annotations

import duckdb

from src.sampling_core.artifacts import (
    SampleBuildResult,
    build_sample,
    build_source_files_metadata,
    check_sample_reuse,
    compute_file_sha256,
    format_sample_filename,
    get_manifest_path,
)
from src.sampling_core.cli import main, run_sampling_cli
from src.sampling_core.engine import (
    materialize_sample_table,
    register_sample_parquet,
)
from src.sampling_core.estimation import (
    estimate_counts,
    format_sample_results,
)


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


__all__ = [
    "SampleBuildResult",
    "build_sample",
    "build_source_files_metadata",
    "check_sample_reuse",
    "compute_file_sha256",
    "estimate_counts",
    "format_sample_filename",
    "format_sample_results",
    "get_manifest_path",
    "main",
    "materialize_sample_table",
    "register_sample_parquet",
    "run_sampling_cli",
    "sample_and_query",
]


if __name__ == "__main__":
    raise SystemExit(main())
