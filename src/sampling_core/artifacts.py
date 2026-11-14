from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

import duckdb

from src.config import (
    CONFIG_VERSION,
    FILTER_VERSION,
    SAMPLING_THREADS,
    validate_sample_rate,
    validate_seed,
)
from src.sampling_core.engine import (
    get_count_parquet_rows_sql,
    get_export_sample_sql,
    get_memory_limit,
    get_threads,
    set_threads,
    validate_output_path,
    validate_source_view,
)


@dataclass(frozen=True)
class SampleBuildResult:
    output_path: Path
    manifest_path: Path
    row_count: int
    build_seconds: float
    reused: bool
    check_seconds: float = 0.0


def compute_file_sha256(file_path: str | Path) -> str:
    path = Path(file_path)
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def format_sample_filename(dataset_id: str, sample_rate: float, seed: int) -> str:
    validate_sample_rate(sample_rate)
    validate_seed(seed)
    rate_token = f"{float(sample_rate):g}"
    return f"{dataset_id}_rate-{rate_token}_seed-{int(seed)}.parquet"


def get_manifest_path(output_path: str | Path) -> Path:
    out = Path(output_path)
    return out.with_suffix(".manifest.json")


def _normalize_period(
    period: tuple[datetime, datetime] | dict[str, str] | None,
) -> dict[str, str] | None:
    if period is None:
        return None
    if isinstance(period, dict):
        return {"start": str(period["start"]), "end": str(period["end"])}
    start, end = period
    return {"start": start.isoformat(), "end": end.isoformat()}


def build_source_files_metadata(
    source_files: Sequence[str | Path] | None,
) -> list[dict[str, Any]]:
    if not source_files:
        return []
    entries: list[dict[str, Any]] = []
    for raw_path in source_files:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        resolved = path.resolve()
        entries.append(
            {
                "path": resolved.as_posix(),
                "sha256": compute_file_sha256(resolved),
                "size_bytes": resolved.stat().st_size,
            }
        )
    return entries


def _resolve_p_and_output(
    p: float | None,
    sample_rate: float | None,
    output: str | Path | None,
    output_path: str | Path | None,
) -> tuple[float, Path]:
    if p is not None and sample_rate is not None and p != sample_rate:
        raise ValueError("Conflicting values provided for p and sample_rate.")
    resolved_p = p if p is not None else sample_rate
    if resolved_p is None:
        raise ValueError("Sample probability p is required.")
    validate_sample_rate(resolved_p)

    if output is not None and output_path is not None and Path(output) != Path(output_path):
        raise ValueError("Conflicting values provided for output and output_path.")
    resolved_output = output if output is not None else output_path
    out_file = validate_output_path(resolved_output)
    return float(resolved_p), out_file


def _expected_manifest_identity(
    *,
    dataset_id: str,
    period: dict[str, str] | None,
    source_files_meta: list[dict[str, Any]],
    p: float,
    seed: int,
    out_file: Path,
    effective_memory_limit: str | None,
    filter_version: str = FILTER_VERSION,
    config_version: str = CONFIG_VERSION,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "sampling_threads": SAMPLING_THREADS,
    }
    if effective_memory_limit is not None:
        settings["memory_limit"] = effective_memory_limit

    return {
        "config_version": config_version,
        "filter_version": filter_version,
        "dataset_id": dataset_id,
        "period": period,
        "source_files": source_files_meta,
        "method": "bernoulli",
        "sample_rate": float(p),
        "seed": int(seed),
        "duckdb_version": duckdb.__version__,
        "settings": settings,
        "output_file": out_file.name,
    }


def check_sample_reuse(
    output_path: str | Path,
    *,
    p: float,
    seed: int,
    con: duckdb.DuckDBPyConnection | None = None,
    dataset_id: str = "custom",
    period: tuple[datetime, datetime] | dict[str, str] | None = None,
    source_files: Sequence[str | Path] | None = None,
    source_files_meta: list[dict[str, Any]] | None = None,
    filter_version: str = FILTER_VERSION,
    config_version: str = CONFIG_VERSION,
) -> tuple[bool, dict[str, Any] | None]:
    """Verifică dacă un eșantion existent și manifestul său pot fi reutilizate în siguranță."""
    out_file = validate_output_path(output_path)
    manifest_file = get_manifest_path(out_file)
    if not out_file.exists() or not manifest_file.exists():
        return False, None

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None

    if not isinstance(manifest, dict):
        return False, None

    if source_files_meta is not None:
        resolved_sources_meta = source_files_meta
    else:
        try:
            resolved_sources_meta = build_source_files_metadata(source_files)
        except FileNotFoundError:
            return False, manifest

    effective_memory_limit = get_memory_limit(con) if con is not None else None

    expected = _expected_manifest_identity(
        dataset_id=dataset_id,
        period=_normalize_period(period),
        source_files_meta=resolved_sources_meta,
        p=p,
        seed=seed,
        out_file=out_file,
        effective_memory_limit=effective_memory_limit,
        filter_version=filter_version,
        config_version=config_version,
    )

    for key, expected_val in expected.items():
        if key == "sample_rate":
            actual_rate = manifest.get("sample_rate")
            if not isinstance(actual_rate, (int, float)) or not math.isclose(
                float(actual_rate), float(expected_val), rel_tol=0.0, abs_tol=1e-12
            ):
                return False, manifest
        elif key == "settings":
            actual_settings = manifest.get("settings")
            if not isinstance(actual_settings, dict):
                return False, manifest
            if actual_settings.get("sampling_threads") != SAMPLING_THREADS:
                return False, manifest
            actual_mem = actual_settings.get("memory_limit")
            if not isinstance(actual_mem, str) or not actual_mem.strip():
                return False, manifest
            if effective_memory_limit is not None and actual_mem != effective_memory_limit:
                return False, manifest
        elif manifest.get(key) != expected_val:
            return False, manifest

    row_count = manifest.get("row_count")
    output_sha256 = manifest.get("output_sha256")
    build_seconds = manifest.get("build_seconds")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        return False, manifest
    if not isinstance(output_sha256, str) or len(output_sha256) != 64:
        return False, manifest
    if (
        isinstance(build_seconds, bool)
        or not isinstance(build_seconds, (int, float))
        or not math.isfinite(float(build_seconds))
        or float(build_seconds) < 0
    ):
        return False, manifest

    if compute_file_sha256(out_file) != output_sha256:
        return False, manifest

    return True, manifest


def _read_parquet_row_count(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    con.execute("SET VARIABLE sample_parquet_path = ?", [str(parquet_path.resolve())])
    row = con.execute(get_count_parquet_rows_sql()).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to read row count from Parquet: {parquet_path}")
    return int(row[0])


def build_sample(
    con: duckdb.DuckDBPyConnection,
    p: float | None = None,
    seed: int = 42,
    output: str | Path | None = None,
    *,
    sample_rate: float | None = None,
    output_path: str | Path | None = None,
    source_view: str = "trips",
    dataset_id: str = "custom",
    period: tuple[datetime, datetime] | dict[str, str] | None = None,
    source_files: Sequence[str | Path] | None = None,
    source_files_meta: list[dict[str, Any]] | None = None,
    filter_version: str = FILTER_VERSION,
    config_version: str = CONFIG_VERSION,
    reuse: bool = False,
    overwrite: bool = False,
) -> SampleBuildResult:
    """Construiește și exportă în Parquet un eșantion Bernoulli reproductibil + manifest JSON."""
    resolved_p, out_file = _resolve_p_and_output(p, sample_rate, output, output_path)
    validate_seed(seed)
    safe_source = validate_source_view(source_view)

    normalized_period = _normalize_period(period)
    resolved_sources_meta = (
        source_files_meta
        if source_files_meta is not None
        else build_source_files_metadata(source_files)
    )
    effective_memory_limit = get_memory_limit(con)
    manifest_file = get_manifest_path(out_file)

    check_start = time.perf_counter()
    if out_file.exists() or manifest_file.exists():
        reusable, existing_manifest = check_sample_reuse(
            out_file,
            p=resolved_p,
            seed=seed,
            con=con,
            dataset_id=dataset_id,
            period=normalized_period,
            source_files_meta=resolved_sources_meta,
            filter_version=filter_version,
            config_version=config_version,
        )
        check_seconds = time.perf_counter() - check_start
        if reuse and reusable and existing_manifest is not None:
            return SampleBuildResult(
                output_path=out_file,
                manifest_path=manifest_file,
                row_count=int(existing_manifest["row_count"]),
                build_seconds=float(existing_manifest["build_seconds"]),
                reused=True,
                check_seconds=check_seconds,
            )
        if not overwrite:
            raise ValueError(
                f"Existing sample or manifest at {out_file} is incompatible or already present; "
                "refusing to reuse or overwrite without explicit overwrite=True."
            )
    else:
        check_seconds = time.perf_counter() - check_start

    export_sql = get_export_sample_sql(safe_source, resolved_p, seed)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Cronometrul măsoară strict exportul eșantionului, fără validarea ulterioară.
    previous_threads = get_threads(con)
    set_threads(con, SAMPLING_THREADS)
    build_start = time.perf_counter()
    try:
        con.execute("SET VARIABLE sample_output_path = ?", [str(out_file.resolve())])
        con.execute(export_sql)
    finally:
        build_seconds = time.perf_counter() - build_start
        set_threads(con, previous_threads)

    if not out_file.exists() or out_file.stat().st_size == 0:
        raise RuntimeError(f"Export failed: Parquet file was not created at {out_file}")

    row_count = _read_parquet_row_count(con, out_file)
    output_sha256 = compute_file_sha256(out_file)

    manifest = _expected_manifest_identity(
        dataset_id=dataset_id,
        period=normalized_period,
        source_files_meta=resolved_sources_meta,
        p=resolved_p,
        seed=seed,
        out_file=out_file,
        effective_memory_limit=effective_memory_limit,
        filter_version=filter_version,
        config_version=config_version,
    )
    manifest["row_count"] = row_count
    manifest["output_sha256"] = output_sha256
    manifest["build_seconds"] = build_seconds

    manifest_file.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return SampleBuildResult(
        output_path=out_file,
        manifest_path=manifest_file,
        row_count=row_count,
        build_seconds=build_seconds,
        reused=False,
        check_seconds=check_seconds,
    )
