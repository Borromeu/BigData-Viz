from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MetricResult:
    status: str
    value: float | None


def _validate_dataframe(df: pd.DataFrame) -> None:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas.DataFrame.")
    if not {"group_key", "value"}.issubset(df.columns):
        raise ValueError("DataFrame requires group_key and value columns.")
    keys = df["group_key"]
    if keys.isna().any() or keys.duplicated().any():
        raise ValueError("group_key values must be non-null and unique.")
    if len(keys):
        kinds = {str(type(value)) for value in keys}
        if len(kinds) != 1:
            raise ValueError("group_key values must use a compatible format.")
    if (not pd.api.types.is_numeric_dtype(df["value"])
            or pd.api.types.is_bool_dtype(df["value"])):
        raise ValueError("value must be numeric.")
    try:
        values = pd.to_numeric(df["value"], errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be numeric.") from exc
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("value must be finite and nonnegative.")


def _merge(exact_df, estimated_df):
    _validate_dataframe(exact_df)
    _validate_dataframe(estimated_df)
    if len(exact_df) and len(estimated_df):
        exact_kinds = {str(type(v)) for v in exact_df["group_key"]}
        estimate_kinds = {str(type(v)) for v in estimated_df["group_key"]}
        if exact_kinds != estimate_kinds:
            raise ValueError("group_key formats must match.")
    merged = pd.merge(exact_df, estimated_df, on="group_key", how="outer",
                       suffixes=("_exact", "_est"), validate="one_to_one",
                       indicator=True)
    # Input NaNs are rejected above; these NaNs are introduced only by the outer join.
    merged["value_exact"] = merged["value_exact"].fillna(0)
    merged["value_est"] = merged["value_est"].fillna(0)
    return merged


def calculate_hours_error(exact_df, estimated_df, *, with_status=False):
    merged = _merge(exact_df, estimated_df)
    total_exact = float(merged["value_exact"].sum())
    total_est = float(merged["value_est"].sum())
    if total_exact == 0:
        result = MetricResult("not_applicable", None)
    elif total_est == 0:
        result = MetricResult("empty_sample", 1.0)
    else:
        result = MetricResult("ok", float(np.abs(merged["value_exact"] - merged["value_est"]).sum() / total_exact))
    return result if with_status else result.value


def calculate_distance_total_variation(exact_df, estimated_df, *, with_status=False):
    merged = _merge(exact_df, estimated_df)
    total_exact = float(merged["value_exact"].sum())
    total_est = float(merged["value_est"].sum())
    if total_exact == 0:
        result = MetricResult("not_applicable", None)
    elif total_est == 0:
        result = MetricResult("empty_sample", None)
    else:
        p_exact = merged["value_exact"] / total_exact
        p_est = merged["value_est"] / total_est
        result = MetricResult("ok", float(0.5 * np.abs(p_exact - p_est).sum()))
    return result if with_status else result.value


def evaluate(exact_rows, estimated_rows, question):
    fn = calculate_hours_error if question in ("hours", "trips_by_hour") else calculate_distance_total_variation
    result = fn(pd.DataFrame(exact_rows, columns=["group_key", "value"]),
                pd.DataFrame(estimated_rows, columns=["group_key", "value"]),
                with_status=True)
    return {"status": result.status, "value": result.value}
