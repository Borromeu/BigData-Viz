import math

import pandas as pd
import plotly.graph_objects as go

DISTANCE_ORDER = ["(0, 1) mile", "[1, 2) miles", "[2, 5) miles",
                  "[5, 10) miles", "[10, +∞) miles"]
DISTANCE_LABELS = dict(zip(("0", "1", "2", "3", "4"), DISTANCE_ORDER))


def plot_distance_distribution(exact_df: pd.DataFrame, estimated_df: pd.DataFrame,
                               sample_rate: float = 1.0, *, status: str = "ok",
                               analysis_period: str = "Unspecified",
                               random_seed: int | None = None,
                               sample_options: dict | None = None) -> go.Figure:
    if isinstance(sample_rate, bool) or not math.isfinite(sample_rate) or not 0 < sample_rate <= 1:
        raise ValueError("sample_rate must be finite and in (0, 1].")
    options = sample_options or {sample_rate: estimated_df}
    rates = list(options)
    if sample_rate not in rates:
        rates.insert(0, sample_rate)
        options = {sample_rate: estimated_df, **options}
    fig = go.Figure()
    exact_total = exact_df["value"].sum()
    exact_values = [float(v / exact_total * 100) if exact_total else 0.0 for v in exact_df["value"]]
    exact_map = dict(zip(exact_df["group_key"].astype(str), exact_values))
    x = DISTANCE_ORDER
    fig.add_bar(x=x, y=[exact_map.get(k, 0.0) for k in ("0", "1", "2", "3", "4")],
                name="Exact (100%)", visible=True)
    for rate in rates:
        frame = options[rate]
        total = frame["value"].sum()
        values = [float(v / total * 100) if total else 0.0 for v in frame["value"]]
        mapping = dict(zip(frame["group_key"].astype(str), values))
        empty = status == "empty_sample" or total == 0
        fig.add_bar(x=x, y=[mapping.get(k, 0.0) for k in ("0", "1", "2", "3", "4")],
                    name=f"Estimated ({rate:g}%)" if rate > 1 else f"Estimated ({rate * 100:g}%)",
                    visible=(rate == sample_rate),
                    hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>")
    buttons = []
    for index, rate in enumerate(rates):
        visible = [True] + [i == index for i in range(len(rates))]
        buttons.append(dict(label=f"{rate * 100:g}%", method="update",
                            args=[{"visible": visible}, {"title": f"Distance distribution — sample {rate * 100:g}%"}]))
    metadata = f"Analysis period: {analysis_period} | Random sample seed: {random_seed if random_seed is not None else 'unspecified'}"
    fig.update_layout(title=f"Distance distribution — sample {sample_rate * 100:g}%",
                      xaxis_title="Distance range", yaxis_title="Share of trips (%)",
                      yaxis=dict(range=[0, 100], ticksuffix="%"), barmode="group",
                      template="plotly_white", meta={"analysis_period": analysis_period, "random_seed": random_seed},
                      annotations=[dict(text=metadata, x=0, y=-0.24, xref="paper", yref="paper", showarrow=False)],
                      updatemenus=[dict(type="dropdown", buttons=buttons, x=1, y=1.15,
                                        xanchor="right", yanchor="top")])
    if status == "empty_sample":
        fig.add_annotation(text="Empty sample: estimated distribution is undefined",
                           x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    return fig
