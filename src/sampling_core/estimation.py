from __future__ import annotations

from collections.abc import Sequence
import math
import numbers
from typing import Any

import pandas as pd

from src.config import (
    CONFIG_VERSION,
    RESULT_COLUMNS,
    validate_sample_rate,
    validate_seed,
)


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
    """Ponderează numărătorile brute cu 1 / p, păstrând cheile și structura."""
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
    """Atașează metadatele cerute de RESULT_COLUMNS peste perechile estimate."""
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
