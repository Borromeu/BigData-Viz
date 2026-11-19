"""A3: benchmark pilot pe Parquet-uri salvate; --fixture este doar o demonstrație."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any

import duckdb

from src.config import (
    CONFIG_VERSION, DUCKDB_MEMORY_LIMIT, FILTER_VERSION, PROJECT_ROOT,
    QUERY_THREADS, RESULT_COLUMNS, RUNS_DIR, SAMPLES_DIR, TEMP_DIR,
    DatasetConfig, get_dataset, get_stage,
)
from src.data import MANIFEST_PATH, register_trips, verify_data_manifest
from src.metrics import evaluate
from src.queries import query_counts
from src.sampling import (
    build_sample, build_source_files_metadata, check_sample_reuse,
    compute_file_sha256, estimate_counts, format_sample_filename,
    get_manifest_path, register_sample_parquet,
)

_SAMPLE_CHECK_SQL = (
    PROJECT_ROOT / "src/sql/benchmark_sample_check.sql"
).read_text(encoding="utf-8")

TIMING_COLUMNS = (
    "run_id", "dataset_id", "config_version", "question", "method",
    "sample_rate", "seed", "repeat", "elapsed_seconds",
)
ERROR_COLUMNS = (
    "run_id", "dataset_id", "config_version", "question", "method",
    "sample_rate", "seed", "metric", "value", "status",
)


@dataclass(frozen=True)
class BenchmarkCase:
    question: str
    sample_rate: float = 1.0
    seed: int | None = None

    @property
    def method(self) -> str:
        return "exact" if self.seed is None else "sample"

    @property
    def source(self) -> str:
        return "trips" if self.seed is None else "sample_trips"


def pilot_cases() -> tuple[BenchmarkCase, ...]:
    stage = get_stage("pilot")
    return tuple(
        case
        for question in stage.questions
        for case in (
            BenchmarkCase(question),
            *(BenchmarkCase(question, rate, seed)
              for rate in stage.sample_rates for seed in stage.seeds),
        )
    )


def measure_query(
    con: duckdb.DuckDBPyConnection,
    case: BenchmarkCase,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[list[tuple[str, int]], float]:
    """Include construirea relației și fetchall; exclude ponderarea/exportul."""
    start = clock()
    rows = query_counts(con, case.question, case.source).fetchall()
    elapsed = clock() - start
    if elapsed <= 0:
        raise RuntimeError("Ceasul nu a produs o durată pozitivă.")
    return rows, elapsed


def _configure_connection(con: duckdb.DuckDBPyConnection) -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET threads = {int(QUERY_THREADS)}")
    con.execute("SET memory_limit = ?", [DUCKDB_MEMORY_LIMIT])
    con.execute("SET temp_directory = ?", [str(TEMP_DIR.resolve())])


def _source_metadata(dataset: DatasetConfig, manifest_path: Path) -> list[dict]:
    # Verifică sursele o singură dată, apoi reutilizează hashurile verificate.
    verify_data_manifest(manifest_path, dataset.files)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {entry["filename"]: entry for entry in manifest["files"]}
    return [
        {"path": path.resolve().as_posix(),
         "size_bytes": entries[path.name]["size_bytes"],
         "sha256": entries[path.name]["sha256"]}
        for path in dataset.files
    ]


def _validate_samples(
    con: duckdb.DuckDBPyConnection, dataset: DatasetConfig,
    source_meta: list[dict], samples_dir: Path,
) -> tuple[dict[tuple[float, int], Path], list[dict]]:
    paths = {}
    records = []
    stage = get_stage("pilot")
    con.execute("SET VARIABLE benchmark_start = ?", [dataset.start])
    con.execute("SET VARIABLE benchmark_end = ?", [dataset.end])
    for rate in stage.sample_rates:
        for seed in stage.seeds:
            path = samples_dir / format_sample_filename(dataset.dataset_id, rate, seed)
            reusable, manifest = check_sample_reuse(
                path, p=rate, seed=seed, con=con, dataset_id=dataset.dataset_id,
                period=(dataset.start, dataset.end), source_files_meta=source_meta,
            )
            if not reusable or manifest is None:
                raise ValueError(
                    f"Eșantion lipsă sau incompatibil: {path}. "
                    "Rulează src.sampling pentru datasetul corespunzător."
                )
            register_sample_parquet(con, path)
            count, invalid = con.execute(_SAMPLE_CHECK_SQL).fetchone()
            if count != manifest["row_count"] or invalid:
                raise ValueError(f"Număr de rânduri sau populație invalidă: {path}")
            paths[rate, seed] = path
            records.append({
                "path": str(path.resolve()),
                "manifest_path": str(get_manifest_path(path).resolve()),
                "manifest_sha256": compute_file_sha256(get_manifest_path(path)),
                "metadata": manifest,
            })
    return paths, records


def _environment() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=PROJECT_ROOT, text=True,
                stderr=subprocess.DEVNULL, timeout=5,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            return None

    try:
        ram_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        ram_bytes = None
    packages = {
        name: importlib.metadata.version(name)
        for name in ("duckdb", "pandas", "numpy")
    }
    status = git("status", "--porcelain", "--untracked-files=normal")
    return {
        "commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": None if status is None else bool(status),
        "python": platform.python_version(), "packages": packages,
        "os": platform.platform(), "machine": platform.machine(),
        "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
        "logical_cpus": os.cpu_count(), "ram_bytes": ram_bytes,
    }


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, columns: Sequence[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run_benchmark(
    dataset: DatasetConfig,
    *,
    run_id: str,
    samples_dir: Path = SAMPLES_DIR,
    runs_dir: Path = RUNS_DIR,
    source_manifest: Path = MANIFEST_PATH,
) -> Path:
    """Execută pilotul fără generare de eșantioane și fără suprascrierea rulărilor."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ValueError("run_id: 1–80 caractere, litere/cifre/cratimă/underscore.")
    run_dir = Path(runs_dir) / run_id
    if run_dir.exists():
        raise FileExistsError(f"Rularea există deja: {run_dir}. Alege un run_id nou.")
    source_meta = _source_metadata(dataset, Path(source_manifest))
    cases = pilot_cases()
    stage = get_stage("pilot")
    con = duckdb.connect()
    try:
        _configure_connection(con)
        register_trips(con, dataset.files, dataset.start, dataset.end)
        paths, samples = _validate_samples(con, dataset, source_meta, Path(samples_dir))
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "run_id": run_id, "dataset_id": dataset.dataset_id, "stage": "pilot",
            "data_kind": "fixture" if dataset.dataset_id == "fixture_jan" else "real",
            "status": "incomplete", "started_at": datetime.now(timezone.utc).isoformat(),
            "config_version": CONFIG_VERSION, "filter_version": FILTER_VERSION,
            "period": {"start": dataset.start.isoformat(), "end": dataset.end.isoformat()},
            "source_files": source_meta, "samples": samples,
            "environment": _environment(),
            "code_sha256": {
                str(path.relative_to(PROJECT_ROOT)): compute_file_sha256(path)
                for path in sorted((PROJECT_ROOT / "src").rglob("*"))
                if path.suffix in (".py", ".sql")
            },
            "settings": {"query_threads": QUERY_THREADS, "memory_limit": DUCKDB_MEMORY_LIMIT,
                         "temp_directory": str(TEMP_DIR.resolve())},
            "protocol": {
                "questions": list(stage.questions), "sample_rates": list(stage.sample_rates),
                "seeds": list(stage.seeds), "repeats": stage.repeats,
                "warmups_per_case": 1, "expected_measurements": len(cases) * stage.repeats,
                "timed": "query_counts + fetchall; wall-clock seconds",
                "excluded": ["input checks", "sample registration", "sample construction",
                             "estimation", "metrics", "file exports"],
                "order": "forward on odd repeats; reverse on even repeats",
                "cache": "warm process; no OS/DuckDB cache reset",
            },
        }
        manifest_path = run_dir / "run_manifest.json"
        _write_json(manifest_path, manifest)

        def prepare(case: BenchmarkCase) -> None:
            if case.seed is not None:
                register_sample_parquet(con, paths[case.sample_rate, case.seed])

        try:
            # O încălzire pentru fiecare caz; nu este salvată ca măsurătoare.
            expected = {}
            for case in cases:
                prepare(case)
                expected[case] = query_counts(con, case.question, case.source).fetchall()

            timings = []
            timing_path = run_dir / "timings.csv"
            with timing_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=TIMING_COLUMNS)
                writer.writeheader()
                for repeat in range(1, stage.repeats + 1):
                    order = cases if repeat % 2 else tuple(reversed(cases))
                    for case in order:
                        prepare(case)
                        rows, elapsed = measure_query(con, case)
                        if rows != expected[case]:
                            raise RuntimeError(f"Rezultate diferite între repetări: {case}")
                        row = {
                            "run_id": run_id, "dataset_id": dataset.dataset_id,
                            "config_version": CONFIG_VERSION, "question": case.question,
                            "method": case.method, "sample_rate": case.sample_rate,
                            "seed": case.seed, "repeat": repeat, "elapsed_seconds": elapsed,
                        }
                        writer.writerow(row)
                        handle.flush()
                        timings.append(row)

            results, errors = [], []
            for case in cases:
                raw = expected[case]
                values = estimate_counts(raw, case.sample_rate) if case.seed is not None else raw
                status = "ok" if sum(v for _, v in raw) else (
                    "empty_sample" if case.seed is not None else "not_applicable"
                )
                identity = {
                    "run_id": run_id, "dataset_id": dataset.dataset_id,
                    "config_version": CONFIG_VERSION, "question": case.question,
                    "method": case.method, "sample_rate": case.sample_rate, "seed": case.seed,
                }
                results.extend(
                    {**identity, "group_key": str(key), "value": value, "status": status}
                    for key, value in values
                )
                if case.seed is not None:
                    error = evaluate(expected[BenchmarkCase(case.question)], values, case.question)
                    errors.append({**identity,
                                   "metric": "normalized_absolute_error" if case.question == "hours"
                                   else "total_variation",
                                   **error})
            _write_csv(run_dir / "results.csv", RESULT_COLUMNS, results)
            _write_csv(run_dir / "errors.csv", ERROR_COLUMNS, errors)
            manifest.update(status="complete", measured_queries=len(timings),
                            result_rows=len(results), error_rows=len(errors),
                            finished_at=datetime.now(timezone.utc).isoformat())
            _write_json(manifest_path, manifest)
        except Exception as exc:
            manifest.update(status="incomplete", error=f"{type(exc).__name__}: {exc}")
            _write_json(manifest_path, manifest)
            raise
    finally:
        con.close()
    return run_dir


def prepare_fixture(samples_dir: Path) -> tuple[DatasetConfig, Path]:
    """Pregătește exclusiv fixture-ul; generarea nu intră în benchmark."""
    pilot = get_dataset("jan")
    dataset = DatasetConfig(
        "fixture_jan", (PROJECT_ROOT / "tests/fixtures/trips.csv",), pilot.start, pilot.end,
    )
    source_meta = build_source_files_metadata(dataset.files)
    samples_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = samples_dir / "fixture_source_manifest.json"
    _write_json(source_manifest, {"files": [
        {"filename": dataset.files[0].name, "sha256": source_meta[0]["sha256"],
         "size_bytes": source_meta[0]["size_bytes"]},
    ]})
    con = duckdb.connect()
    try:
        _configure_connection(con)
        register_trips(con, dataset.files, dataset.start, dataset.end)
        stage = get_stage("pilot")
        for rate in stage.sample_rates:
            for seed in stage.seeds:
                build_sample(
                    con, p=rate, seed=seed,
                    output=samples_dir / format_sample_filename(dataset.dataset_id, rate, seed),
                    dataset_id=dataset.dataset_id, period=(dataset.start, dataset.end),
                    source_files_meta=source_meta, reuse=True,
                )
    finally:
        con.close()
    return dataset, source_manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["pilot"], default="pilot")
    parser.add_argument("--dataset", choices=["jan"], default="jan")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--fixture", action="store_true",
                        help="Demonstrație pe 20 de rânduri; NU reprezintă rezultate TLC reale.")
    args = parser.parse_args(argv)
    try:
        samples_dir = args.samples_dir or (
            SAMPLES_DIR / "fixture" if args.fixture else SAMPLES_DIR
        )
        if args.fixture:
            dataset, source_manifest = prepare_fixture(samples_dir)
        else:
            dataset, source_manifest = get_dataset(args.dataset), MANIFEST_PATH
        run_dir = run_benchmark(
            dataset, run_id=args.run_id, samples_dir=samples_dir,
            runs_dir=args.runs_dir, source_manifest=source_manifest,
        )
    except Exception as exc:
        print(f"[Benchmark] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    label = "FIXTURE — demonstrație" if args.fixture else "TLC — date reale"
    print(f"[Benchmark] {label}; {dataset.dataset_id}; 6 cazuri × 3 repetări = 18 măsurători")
    print(f"[Benchmark] Rezultate: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())