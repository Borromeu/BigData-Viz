import argparse
import json
import math
import numbers
import time
from pathlib import Path
import duckdb
import pandas as pd


def _validate_probability(p):
    """Validează dacă probabilitatea p este un număr real în intervalul (0, 1]."""
    if isinstance(p, bool) or not isinstance(p, numbers.Real):
        raise ValueError("p must be a finite number in (0, 1].")
    if not math.isfinite(float(p)) or not 0 < p <= 1:
        raise ValueError("p must be a finite number in (0, 1].")


def estimate_counts(counts, p):
    """Task S2: Aplică ponderarea 1/p asupra rezultatelor numărate."""
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
    """Scalare individuală pentru o valoare numerică."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("counts must be numeric.")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("counts must be finite and nonnegative.")
    return value / float(p)


def build_sample_view(con, source_view="trips", sample_rate=0.10, seed=42):
    """Task S1: Creează o vedere temporară eșantionată Bernoulli cu seed fix."""
    _validate_probability(sample_rate)

    # Setare critică pentru reproductibilitate pe un singur thread în DuckDB
    con.execute("SET threads = 1;")

    query = f"""
        CREATE OR REPLACE TEMP VIEW sample_trips AS 
        SELECT * FROM {source_view} 
        USING SAMPLE {sample_rate * 100}% (bernoulli, {seed});
    """
    con.execute(query)


def sample_and_query(con, question="hours", sample_rate=0.10, seed=42, source_view="trips"):
    """Task S3: Execută eșantionarea, interogarea comună și ponderarea 1/p."""
    from src.queries import query_counts

    # 1. Creează vederea eșantionată Bernoulli (Task S1)
    build_sample_view(con, source_view=source_view, sample_rate=sample_rate, seed=seed)

    # 2. Rulează interogarea SQL peste eșantion
    raw_counts = query_counts(con, question=question, source="sample_trips")

    # 3. Aplică estimatorul 1/p peste rezultate (Task S2)
    return estimate_counts(raw_counts, p=sample_rate)


def build_sample(con, sample_rate=0.10, seed=42, output_path=None, source_view="trips"):
    """Task S4 & S5: Construiește eșantionul Parquet, salvează metadatele și măsoară timpul."""
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