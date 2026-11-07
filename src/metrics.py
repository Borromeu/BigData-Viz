import pandas as pd
import numpy as np

def calculate_hours_error(exact_df, estimated_df):
    merged = pd.merge(
        exact_df,
        estimated_df,
        on="group_key",
        how="outer",
        suffixes=("_exact", "_est")
    ).fillna(0)

    abs_diff = np.abs(
        merged["value_exact"] - merged["value_est"]
    ).sum()

    total_exact = merged["value_exact"].sum()

    if total_exact == 0:
        if merged["value_est"].sum() == 0:
            return 0.0
        raise ValueError("Totalul exact este zero.")

    return float(abs_diff / total_exact)


def calculate_distance_total_variation(exact_df, estimated_df):
    merged = pd.merge(
        exact_df,
        estimated_df,
        on="group_key",
        how="outer",
        suffixes=("_exact", "_est")
    ).fillna(0)

    total_exact = merged["value_exact"].sum()
    total_est = merged["value_est"].sum()

    if total_exact == 0 and total_est == 0:
        return 0.0

    if total_exact == 0 or total_est == 0:
        return 1.0

    p_exact = merged["value_exact"] / total_exact
    p_est = merged["value_est"] / total_est

    return float(0.5 * np.abs(p_exact - p_est).sum())