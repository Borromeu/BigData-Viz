import math
import numbers

import pandas as pd


def _validate_probability(p):
    if isinstance(p, bool) or not isinstance(p, numbers.Real):
        raise ValueError("p must be a finite number in (0, 1].")
    if not math.isfinite(float(p)) or not 0 < p <= 1:
        raise ValueError("p must be a finite number in (0, 1].")


def estimate_counts(counts, p):
    """Apply inverse-probability weighting once to raw grouped counts."""
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
