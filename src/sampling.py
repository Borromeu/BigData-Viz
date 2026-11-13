import argparse
import json
import math
import numbers
import time
from pathlib import Path
import duckdb
import pandas as pd


def _validate_probability(p):
    if isinstance(p, bool) or not isinstance(p, numbers.Real):
        raise ValueError("p must be a finite number in (0, 1].")
    if not math.isfinite(float(p)) or not 0 < p <= 1:
        raise ValueError("p must be a finite number in (0, 1].")


def estimate_counts(counts, p):
    _validate_probability(p)
    if isinstance(counts, pd.DataFrame):
        if "value" not in counts.columns:
            raise ValueError("counts DataFrame must contain a 'value' column.")
        result = counts.copy()
        values = pd.to_numeric(result["value"], errors="raise")
        if not values.map(math.isfinite).all() or (values < 0).any():
            raise ValueError("counts must be finite and nonnegative.")
        result["value"] = values / float(p)
        return result
    if isinstance(counts, dict):
        return {key: _estimate_value(value, p) for key, value in counts.items()}
    return [_estimate_value(value, p) for value in counts]


def _estimate_value(value, p):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("counts must be numeric.")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("counts must be finite and nonnegative.")
    return value / float(p)


def build_sample_view(con, source_view="trips", sample_rate=0.10, seed=42):
    _validate_probability(sample_rate)

    con.execute("SET threads = 1;")

    query = f"""
        CREATE OR REPLACE TEMP VIEW sample_trips AS 
        SELECT * FROM {source_view} 
        USING SAMPLE {sample_rate * 100}% (bernoulli, {seed});
    """
    con.execute(query)


def sample_and_query(con, question="hours", sample_rate=0.10, seed=42, source_view="trips"):
    from src.queries import query_counts

    build_sample_view(con, source_view=source_view, sample_rate=sample_rate, seed=seed)

    raw_counts = query_counts(con, question=question, source="sample_trips")

    return estimate_counts(raw_counts, p=sample_rate)


def build_sample(con, sample_rate=0.10, seed=42, output_path=None, source_view="trips"):
    _validate_probability(sample_rate)
    start_time = time.perf_counter()

    con.execute("SET threads = 1;")
    query = f"""
        SELECT * FROM {source_view}
        USING SAMPLE {sample_rate * 100}% (bernoulli, {seed});
    """

    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY ({query}) TO '{out_file}' (FORMAT PARQUET);")

    build_seconds = time.perf_counter() - start_time
    return build_seconds
def main():
    parser = argparse.ArgumentParser(description="Generare eșantioane Bernoulli DuckDB")
    parser.add_argument("--stage", choices=["pilot", "final"], default="pilot", help="Etapa proiectului")
    parser.add_argument("--dataset", choices=["jan", "q1", "all"], default="jan", help="Setul de date")
    args = parser.parse_args()

    print(f"[Sampling CLI] Etapa: {args.stage} | Dataset: {args.dataset}")
    print("[Sampling CLI] Modulul de eșantionare este pregătit pentru generarea fișierelor Parquet.")


if __name__ == "__main__":
    main()