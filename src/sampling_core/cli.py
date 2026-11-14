from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import duckdb

from src.config import (
    DUCKDB_MEMORY_LIMIT,
    SAMPLES_DIR,
    DatasetConfig,
    create_output_directories,
    get_dataset,
    get_stage,
)
from src.sampling_core.artifacts import (
    build_sample,
    build_source_files_metadata,
    format_sample_filename,
)

RegisterTripsFn = Callable[[duckdb.DuckDBPyConnection, Sequence[Path], datetime, datetime], None]


def _resolve_register_trips(register_trips_fn: RegisterTripsFn | None) -> RegisterTripsFn:
    if register_trips_fn is not None:
        return register_trips_fn
    from src.data import register_trips  # type: ignore import-not-found

    return register_trips


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
    register_trips_fn: RegisterTripsFn | None = None,
) -> list[dict[str, Any]]:
    stage_cfg = get_stage(stage)
    dataset_cfg = get_dataset(dataset)
    input_files = _resolve_dataset_files(dataset_cfg, raw_dir)

    missing_files = [str(path) for path in input_files if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            f"Missing required raw dataset file(s) for {dataset!r}: {', '.join(missing_files)}"
        )

    register_fn = _resolve_register_trips(register_trips_fn)

    # Calculăm identitatea și hash-urile surselor o singură dată per dataset.
    source_files_meta = build_source_files_metadata(input_files)

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
        register_fn(con, input_files, dataset_cfg.start, dataset_cfg.end)

        for rate in stage_cfg.sample_rates:
            for seed in stage_cfg.seeds:
                filename = format_sample_filename(dataset_cfg.dataset_id, rate, seed)
                out_path = target_dir / filename
                result = build_sample(
                    con,
                    p=rate,
                    seed=seed,
                    output=out_path,
                    source_view="trips",
                    dataset_id=dataset_cfg.dataset_id,
                    period=(dataset_cfg.start, dataset_cfg.end),
                    source_files_meta=source_files_meta,
                    reuse=True,
                )
                generated.append(
                    {
                        "sample_rate": rate,
                        "seed": seed,
                        "output_path": str(result.output_path),
                        "manifest_path": str(result.manifest_path),
                        "row_count": result.row_count,
                        "build_seconds": result.build_seconds,
                        "check_seconds": result.check_seconds,
                        "reused": result.reused,
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
        status_tag = (
            f"reused (original build {item['build_seconds']:.3f}s)"
            if item["reused"]
            else f"built in {item['build_seconds']:.3f}s"
        )
        print(
            f"  - rate={item['sample_rate']} seed={item['seed']} "
            f"rows={item['row_count']} ({status_tag}) -> {item['output_path']}"
        )
    return 0
