from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
import hashlib
import json
import math
import numbers
from pathlib import Path
import sys
import time
from typing import Any

import duckdb
import pandas as pd

from src.config import (
    CONFIG_VERSION,
    DUCKDB_MEMORY_LIMIT,
    FILTER_VERSION,
    RAW_DIR,
    RESULT_COLUMNS,
    SAMPLING_THREADS,
    SAMPLES_DIR,
    DatasetConfig,
    create_output_directories,
    get_dataset,
    get_stage,
    validate_sample_rate,
    validate_seed,
)

SQL_DIR = Path(__file__).resolve().parent / "sql"

ALLOWED_SOURCE_VIEWS = frozenset({"trips"})
ALLOWED_SAMPLE_TARGETS = frozenset({"sample_trips"})

_SQL_FILES = {
    "sample_bernoulli": SQL_DIR / "sample_bernoulli.sql",
    "create_sample_view": SQL_DIR / "create_sample_view.sql",
    "materialize_sample_table": SQL_DIR / "materialize_sample_table.sql",
    "export_sample_parquet": SQL_DIR / "export_sample_parquet.sql",
    "register_sample_parquet": SQL_DIR / "register_sample_parquet.sql",
    "count_parquet_rows": SQL_DIR / "count_parquet_rows.sql",
    "register_trips_fallback": SQL_DIR / "register_trips_fallback.sql",
}


def _load_sql(template_key: str) -> str:
    if template_key not in _SQL_FILES:
        raise ValueError(f"Unknown SQL template: {template_key!r}")
    return _SQL_FILES[template_key].read_text(encoding="utf-8").strip()


_SAMPLE_BERNOULLI_SQL = _load_sql("sample_bernoulli")
_CREATE_SAMPLE_VIEW_SQL = _load_sql("create_sample_view")
_MATERIALIZE_SAMPLE_TABLE_SQL = _load_sql("materialize_sample_table")
_EXPORT_SAMPLE_PARQUET_SQL = _load_sql("export_sample_parquet")
_REGISTER_SAMPLE_PARQUET_SQL = _load_sql("register_sample_parquet")
_COUNT_PARQUET_ROWS_SQL = _load_sql("count_parquet_rows")
_REGISTER_TRIPS_FALLBACK_SQL = _load_sql("register_trips_fallback")


def _validate_source_view(source_view: str) -> str:
    if not isinstance(source_view, str) or source_view not in ALLOWED_SOURCE_VIEWS:
        raise ValueError(
            f"Unknown SQL source {source_view!r}; allowed: {sorted(ALLOWED_SOURCE_VIEWS)}"
        )
    return source_view


def _validate_output_path(output: str | Path | None) -> Path:
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
    out_file = _validate_output_path(resolved_output)
    return float(resolved_p), out_file


def _estimate_value(value: Any, p: float) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("counts must be numeric.")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("counts must be finite and nonnegative.")
    estimated = numeric / float(p)
    if not math.isfinite(estimated):
        raise ValueError("Estimated count overflowed to a non-finite value.")
    return estimated


def estimate_counts(counts: Any, p: float) -> Any:
    validate_sample_rate(p)
    p_float = float(p)

    if isinstance(counts, pd.DataFrame):
        if "value" not in counts.columns:
            raise ValueError("counts DataFrame must contain a 'value' column.")
        if pd.api.types.is_bool_dtype(counts["value"]):
            raise ValueError("counts must be numeric.")
        result = counts.copy()
        result["value"] = [_estimate_value(v, p_float) for v in result["value"]]
        return result

    if isinstance(counts, dict):
        return {key: _estimate_value(value, p_float) for key, value in counts.items()}

    if hasattr(counts, "fetchall"):
        rows = counts.fetchall()
        return [(key, _estimate_value(value, p_float)) for key, value in rows]

    if isinstance(counts, (str, bytes)) or not isinstance(counts, Sequence):
        raise ValueError("Unsupported counts container type.")

    items = list(counts)
    if not items:
        return []

    if isinstance(items[0], (tuple, list)):
        estimated_pairs: list[tuple[Any, float]] = []
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("Pair entries must have length 2: (group_key, count).")
            key, value = item
            estimated_pairs.append((key, _estimate_value(value, p_float)))
        return estimated_pairs

    estimated_list: list[float] = []
    for value in items:
        if isinstance(value, (tuple, list)):
            raise ValueError("Mixed pair and scalar entries are not allowed.")
        estimated_list.append(_estimate_value(value, p_float))
    return estimated_list


def _get_threads(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT current_setting('threads')").fetchone()
    if row is None:
        raise RuntimeError("Could not read DuckDB threads setting.")
    return int(row[0])


def _set_threads(con: duckdb.DuckDBPyConnection, threads: int) -> None:
    con.execute(f"SET threads = {int(threads)}")


def _format_bernoulli_sql(template: str, source_view: str, p: float, seed: int) -> str:
    safe_source = _validate_source_view(source_view)
    validate_sample_rate(p)
    validate_seed(seed)
    sample_percent = repr(float(p) * 100.0)
    return (
        template.replace("{source_view}", safe_source)
        .replace("{sample_percent}", sample_percent)
        .replace("{seed}", str(int(seed)))
    )


def build_sample_view(
    con: duckdb.DuckDBPyConnection,
    source_view: str = "trips",
    sample_rate: float = 0.10,
    seed: int = 42,
) -> None:
    sql = _format_bernoulli_sql(_CREATE_SAMPLE_VIEW_SQL, source_view, sample_rate, seed)
    previous_threads = _get_threads(con)
    _set_threads(con, SAMPLING_THREADS)
    try:
        con.execute(sql)
    finally:
        _set_threads(con, previous_threads)


def materialize_sample_table(
    con: duckdb.DuckDBPyConnection,
    p: float = 0.10,
    seed: int = 42,
    source_view: str = "trips",
) -> float:
    sql = _format_bernoulli_sql(_MATERIALIZE_SAMPLE_TABLE_SQL, source_view, p, seed)
    previous_threads = _get_threads(con)
    start_time = time.perf_counter()
    _set_threads(con, SAMPLING_THREADS)
    try:
        con.execute(sql)
    finally:
        _set_threads(con, previous_threads)
    return time.perf_counter() - start_time


def register_sample_parquet(
    con: duckdb.DuckDBPyConnection,
    sample_path: str | Path,
) -> None:
    path = _validate_output_path(sample_path)
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
    from src.queries import query_counts

    materialize_sample_table(con, p=sample_rate, seed=seed, source_view=source_view)
    raw_counts = query_counts(con, question=question, source="sample_trips")
    return estimate_counts(raw_counts, p=sample_rate)


def format_sample_results(
    estimated_rows: Sequence[tuple[str, float]],
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    sample_rate: float,
    seed: int,
    config_version: str = CONFIG_VERSION,
) -> list[dict[str, Any]]:
    validate_sample_rate(sample_rate)
    validate_seed(seed)

    pairs = list(estimated_rows)
    total = sum(float(val) for _, val in pairs)
    status = "empty_sample" if total == 0 else "ok"

    formatted: list[dict[str, Any]] = []
    for group_key, value in pairs:
        row = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "config_version": config_version,
            "question": question,
            "method": "sample",
            "sample_rate": float(sample_rate),
            "seed": int(seed),
            "group_key": str(group_key),
            "value": float(value),
            "status": status,
        }
        formatted.append({col: row[col] for col in RESULT_COLUMNS})
    return formatted


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


def _build_source_files_metadata(
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
    filter_version: str = FILTER_VERSION,
    config_version: str = CONFIG_VERSION,
) -> dict[str, Any]:
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
        "settings": {
            "sampling_threads": SAMPLING_THREADS,
            "memory_limit": DUCKDB_MEMORY_LIMIT,
        },
        "output_file": out_file.name,
    }


def check_sample_reuse(
    output_path: str | Path,
    *,
    p: float,
    seed: int,
    dataset_id: str = "custom",
    period: tuple[datetime, datetime] | dict[str, str] | None = None,
    source_files: Sequence[str | Path] | None = None,
    filter_version: str = FILTER_VERSION,
    config_version: str = CONFIG_VERSION,
) -> tuple[bool, dict[str, Any] | None]:
    out_file = _validate_output_path(output_path)
    manifest_file = get_manifest_path(out_file)
    if not out_file.exists() or not manifest_file.exists():
        return False, None

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None

    if not isinstance(manifest, dict):
        return False, None

    try:
        source_files_meta = _build_source_files_metadata(source_files)
    except FileNotFoundError:
        return False, manifest

    expected = _expected_manifest_identity(
        dataset_id=dataset_id,
        period=_normalize_period(period),
        source_files_meta=source_files_meta,
        p=p,
        seed=seed,
        out_file=out_file,
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
        elif manifest.get(key) != expected_val:
            return False, manifest

    row_count = manifest.get("row_count")
    output_sha256 = manifest.get("output_sha256")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        return False, manifest
    if not isinstance(output_sha256, str) or len(output_sha256) != 64:
        return False, manifest

    if compute_file_sha256(out_file) != output_sha256:
        return False, manifest

    return True, manifest


def _read_parquet_row_count(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    con.execute("SET VARIABLE sample_parquet_path = ?", [str(parquet_path.resolve())])
    row = con.execute(_COUNT_PARQUET_ROWS_SQL).fetchone()
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
    filter_version: str = FILTER_VERSION,
    config_version: str = CONFIG_VERSION,
    reuse: bool = False,
    overwrite: bool = False,
) -> float:
    resolved_p, out_file = _resolve_p_and_output(p, sample_rate, output, output_path)
    validate_seed(seed)
    safe_source = _validate_source_view(source_view)

    normalized_period = _normalize_period(period)
    source_files_meta = _build_source_files_metadata(source_files)
    manifest_file = get_manifest_path(out_file)

    if out_file.exists() or manifest_file.exists():
        reusable, _ = check_sample_reuse(
            out_file,
            p=resolved_p,
            seed=seed,
            dataset_id=dataset_id,
            period=normalized_period,
            source_files=source_files,
            filter_version=filter_version,
            config_version=config_version,
        )
        if reuse and reusable:
            return 0.0
        if not overwrite:
            raise ValueError(
                f"Existing sample or manifest at {out_file} is incompatible or already present; "
                "refusing to reuse or overwrite without explicit overwrite=True."
            )

    export_sql = _format_bernoulli_sql(
        _EXPORT_SAMPLE_PARQUET_SQL,
        safe_source,
        resolved_p,
        seed,
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    previous_threads = _get_threads(con)
    start_time = time.perf_counter()
    _set_threads(con, SAMPLING_THREADS)
    try:
        con.execute("SET VARIABLE sample_output_path = ?", [str(out_file.resolve())])
        con.execute(export_sql)
    finally:
        _set_threads(con, previous_threads)

    if not out_file.exists() or out_file.stat().st_size == 0:
        raise RuntimeError(f"Export failed: Parquet file was not created at {out_file}")

    row_count = _read_parquet_row_count(con, out_file)
    build_seconds = time.perf_counter() - start_time

    manifest = _expected_manifest_identity(
        dataset_id=dataset_id,
        period=normalized_period,
        source_files_meta=source_files_meta,
        p=resolved_p,
        seed=seed,
        out_file=out_file,
        filter_version=filter_version,
        config_version=config_version,
    )
    manifest["row_count"] = row_count
    manifest["output_sha256"] = compute_file_sha256(out_file)
    manifest["build_seconds"] = build_seconds

    manifest_file.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return build_seconds


def _register_population_trips(
    con: duckdb.DuckDBPyConnection,
    files: Sequence[Path],
    start: datetime,
    end: datetime,
) -> None:
    try:
        from src.data import register_trips  # type: ignore import-not-found

        register_trips(con, files, start, end)
        return
    except ImportError:
        pass

    var_refs: list[str] = []
    for idx, file_path in enumerate(files):
        var_name = f"raw_parquet_file_{idx}"
        con.execute(f"SET VARIABLE {var_name} = ?", [str(Path(file_path).resolve())])
        var_refs.append(f"getvariable('{var_name}')")

    parquet_vars_sql = f"[{', '.join(var_refs)}]"
    con.execute("SET VARIABLE period_start = ?", [start.isoformat(sep=" ")])
    con.execute("SET VARIABLE period_end = ?", [end.isoformat(sep=" ")])
    sql = _REGISTER_TRIPS_FALLBACK_SQL.replace("{parquet_vars}", parquet_vars_sql)
    con.execute(sql)


def _resolve_dataset_files(dataset_cfg: DatasetConfig, raw_dir: Path | None) -> tuple[Path, ...]:
    if raw_dir is None:
        return dataset_cfg.files
    base_dir = Path(raw_dir)
    return tuple(base_dir / path.name for path in dataset_cfg.files)


def run_sampling_cli(
    stage: str = "pilot",
    dataset: str = "jan",
    *,
    raw_dir: Path | None = None,
    samples_dir: Path | None = None,
) -> list[dict[str, Any]]:
    stage_cfg = get_stage(stage)
    dataset_cfg = get_dataset(dataset)
    input_files = _resolve_dataset_files(dataset_cfg, raw_dir)

    missing_files = [str(path) for path in input_files if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            f"Missing required raw dataset file(s) for {dataset!r}: {', '.join(missing_files)}"
        )

    if samples_dir is None:
        create_output_directories()
        target_dir = SAMPLES_DIR
    else:
        target_dir = Path(samples_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    generated: list[dict[str, Any]] = []
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit = '{DUCKDB_MEMORY_LIMIT}'")
        _register_population_trips(con, input_files, dataset_cfg.start, dataset_cfg.end)

        for rate in stage_cfg.sample_rates:
            for seed in stage_cfg.seeds:
                filename = format_sample_filename(dataset_cfg.dataset_id, rate, seed)
                out_path = target_dir / filename
                reused, _ = check_sample_reuse(
                    out_path,
                    p=rate,
                    seed=seed,
                    dataset_id=dataset_cfg.dataset_id,
                    period=(dataset_cfg.start, dataset_cfg.end),
                    source_files=input_files,
                )
                duration = build_sample(
                    con,
                    p=rate,
                    seed=seed,
                    output=out_path,
                    source_view="trips",
                    dataset_id=dataset_cfg.dataset_id,
                    period=(dataset_cfg.start, dataset_cfg.end),
                    source_files=input_files,
                    reuse=True,
                )
                manifest = json.loads(get_manifest_path(out_path).read_text(encoding="utf-8"))
                generated.append(
                    {
                        "sample_rate": rate,
                        "seed": seed,
                        "output_path": str(out_path),
                        "manifest_path": str(get_manifest_path(out_path)),
                        "row_count": int(manifest["row_count"]),
                        "build_seconds": duration,
                        "reused": reused,
                    }
                )
    finally:
        con.close()

    return generated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generare eșantioane Bernoulli DuckDB")
    parser.add_argument(
        "--stage",
        choices=["pilot", "final"],
        default="pilot",
        help="Etapa proiectului (pilot sau final)",
    )
    parser.add_argument(
        "--dataset",
        choices=["jan", "q1"],
        default="jan",
        help="Setul de date (jan sau q1)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Director opțional pentru fișierele Parquet brute (implicit data/raw)",
    )
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=None,
        help="Director opțional pentru eșantioanele generate (implicit data/samples)",
    )
    args = parser.parse_args(argv)

    try:
        results = run_sampling_cli(
            stage=args.stage,
            dataset=args.dataset,
            raw_dir=args.raw_dir,
            samples_dir=args.samples_dir,
        )
    except Exception as exc:
        print(f"[Sampling CLI] Error: {exc}", file=sys.stderr)
        return 1

    print(f"[Sampling CLI] Stage: {args.stage} | Dataset: {args.dataset}")
    for item in results:
        status_tag = "reused" if item["reused"] else f"built in {item['build_seconds']:.3f}s"
        print(
            f"  - rate={item['sample_rate']} seed={item['seed']} "
            f"rows={item['row_count']} ({status_tag}) -> {item['output_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())