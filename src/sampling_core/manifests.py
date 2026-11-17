from __future__ import annotations

from collections.abc import Sequence
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb

from src.config import (
    CONFIG_VERSION,
    FILTER_VERSION,
    SAMPLING_THREADS,
)
from src.sampling_core.engine import (
    get_memory_limit,
    validate_output_path,
)


def compute_file_sha256(file_path: str | Path) -> str:
    path = Path(file_path)
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def format_sample_filename(dataset_id: str, sample_rate: float, seed: int) -> str:
    from src.config import validate_sample_rate, validate_seed

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


BUILD_LOG_COLUMNS = (
    "dataset_id",
    "sample_rate",
    "seed",
    "row_count",
    "size_bytes",
    "build_seconds",
    "check_seconds",
    "reused",
    "output_file",
    "manifest_file",
)


def update_build_log(
    log_path: str | Path,
    entries: Sequence[dict[str, Any]],
) -> Path:
    """Înregistrează sau actualizează costurile eșantioanelor în build_log.csv."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row.get("dataset_id", ""), row.get("sample_rate", ""), int(row.get("seed", 0)))
                    existing_rows[key] = row
        except Exception:
            existing_rows.clear()

    for item in entries:
        rate_str = f"{float(item['sample_rate']):g}"
        key = (str(item["dataset_id"]), rate_str, int(item["seed"]))
        existing_rows[key] = {
            "dataset_id": str(item["dataset_id"]),
            "sample_rate": rate_str,
            "seed": int(item["seed"]),
            "row_count": int(item["row_count"]),
            "size_bytes": int(item.get("size_bytes", 0)),
            "build_seconds": f"{float(item['build_seconds']):.6f}",
            "check_seconds": f"{float(item.get('check_seconds', 0.0)):.6f}",
            "reused": str(bool(item.get("reused", False))),
            "output_file": Path(item.get("output_path", item.get("output_file", ""))).name,
            "manifest_file": Path(item.get("manifest_path", item.get("manifest_file", ""))).name,
        }

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BUILD_LOG_COLUMNS)
        writer.writeheader()
        for row in existing_rows.values():
            writer.writerow({col: row.get(col, "") for col in BUILD_LOG_COLUMNS})

    return path
