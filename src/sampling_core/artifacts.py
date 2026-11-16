from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import tempfile
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
from src.sampling_core.manifests import (
    _expected_manifest_identity,
    _normalize_period,
    build_source_files_metadata,
    check_sample_reuse,
    compute_file_sha256,
    format_sample_filename,
    get_manifest_path,
)


@dataclass(frozen=True)
class SampleBuildResult:
    output_path: Path
    manifest_path: Path
    row_count: int
    build_seconds: float
    reused: bool
    check_seconds: float = 0.0
    size_bytes: int = 0


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


def _read_parquet_row_count(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    con.execute("SET VARIABLE sample_parquet_path = ?", [str(parquet_path.resolve())])
    row = con.execute(get_count_parquet_rows_sql()).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to read row count from Parquet: {parquet_path}")
    return int(row[0])


def _publish_artifact_pair(
    new_sample: Path,
    new_manifest: Path,
    sample_path: Path,
    manifest_path: Path,
    staging_dir: Path,
) -> None:
    """Publica ambele fisiere; revine la versiunile vechi daca publicarea esueaza."""
    old_sample = staging_dir / "previous_sample.backup"
    old_manifest = staging_dir / "previous_manifest.backup"
    had_sample = sample_path.exists()
    had_manifest = manifest_path.exists()

    # Facem copiile de siguranta inainte sa modificam vreun fisier publicat.
    if had_sample:
        shutil.copy2(sample_path, old_sample)
    if had_manifest:
        shutil.copy2(manifest_path, old_manifest)

    try:
        # replace() inlocuieste un fisier existent, inclusiv pe Windows.
        new_sample.replace(sample_path)
        new_manifest.replace(manifest_path)
    except Exception:
        # Daca al doilea replace esueaza, restauram si primul fisier.
        if had_sample:
            old_sample.replace(sample_path)
        elif sample_path.exists():
            sample_path.unlink()

        if had_manifest:
            old_manifest.replace(manifest_path)
        elif manifest_path.exists():
            manifest_path.unlink()
        raise


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
                size_bytes=out_file.stat().st_size,
            )
        if not overwrite:
            raise ValueError(
                f"Existing sample or manifest at {out_file} is incompatible or already present; "
                "refusing to reuse or overwrite without explicit overwrite=True."
            )
    else:
        check_seconds = time.perf_counter() - check_start

    export_sql = get_export_sample_sql()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Staging-ul sta pe acelasi sistem de fisiere cu destinatia finala.
    # Un export esuat nu atinge esantionul si manifestul existente.
    with tempfile.TemporaryDirectory(
        prefix=".sampling_stage_",
        dir=out_file.parent,
    ) as temp_dir_name:
        staging_dir = Path(temp_dir_name)
        staged_sample = staging_dir / out_file.name
        staged_manifest = staging_dir / manifest_file.name

        previous_threads = get_threads(con)
        set_threads(con, SAMPLING_THREADS)
        build_start = time.perf_counter()
        try:
            con.execute(
                "SET VARIABLE sample_output_path = ?",
                [str(staged_sample.resolve())],
            )

            # Valorile p si seed raman in Relational API, nu in SQL.
            sample_relation = con.table(safe_source).sample(
                percent=resolved_p * 100.0,
                seed=int(seed),
                method="bernoulli",
            )
            con.register("__sampling_relation", sample_relation)
            try:
                con.execute(export_sql)
            finally:
                con.unregister("__sampling_relation")
        finally:
            # Cronometrul nu include validarea si publicarea artefactelor.
            build_seconds = time.perf_counter() - build_start
            set_threads(con, previous_threads)

        if not staged_sample.exists() or staged_sample.stat().st_size == 0:
            raise RuntimeError(
                f"Export failed: Parquet file was not created at {staged_sample}"
            )

        # Validam si citim noul Parquet inainte sa atingem versiunea veche.
        row_count = _read_parquet_row_count(con, staged_sample)
        output_sha256 = compute_file_sha256(staged_sample)

        # Manifestul descrie calea PUBLICATA, nu calea temporara.
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

        staged_manifest.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Validam si JSON-ul nou inainte de publicare.
        json.loads(staged_manifest.read_text(encoding="utf-8"))

        _publish_artifact_pair(
            staged_sample,
            staged_manifest,
            out_file,
            manifest_file,
            staging_dir,
        )

    return SampleBuildResult(
        output_path=out_file,
        manifest_path=manifest_file,
        row_count=row_count,
        build_seconds=build_seconds,
        reused=False,
        check_seconds=check_seconds,
        size_bytes=out_file.stat().st_size,
    )
