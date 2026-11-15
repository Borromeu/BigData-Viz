from __future__ import annotations

import duckdb

from src.sampling_core.artifacts import (
    SampleBuildResult,
    build_sample,
)
from src.sampling_core.cli import main, run_sampling_cli
from src.sampling_core.engine import (
    materialize_sample_table,
    register_sample_parquet,
    sample_and_query,
)
from src.sampling_core.estimation import (
    estimate_counts,
    format_sample_results,
)
from src.sampling_core.manifests import (
    build_source_files_metadata,
    check_sample_reuse,
    compute_file_sha256,
    format_sample_filename,
    get_manifest_path,
    update_build_log,
)


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
    "update_build_log",
]


if __name__ == "__main__":
    raise SystemExit(main())
