"""A4: graficul curselor după ora zilei, din rezultatele A3."""

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path

import plotly.graph_objects as go

HOURS = tuple(f"{hour:02d}" for hour in range(24))


def build_hours_figure(rows, manifest, metric_values=None):
    """Compară agregarea exactă cu estimările salvate pentru un singur seed."""
    if manifest["status"] != "complete" or manifest["stage"] != "pilot":
        raise ValueError("Graficul are nevoie de o rulare pilot completă.")

    rates = tuple(float(rate) for rate in manifest["protocol"]["sample_rates"])
    seeds = manifest["protocol"]["seeds"]
    if not rates or len(seeds) != 1:
        raise ValueError("Pilotul trebuie să aibă procente de eșantionare și un singur seed.")
    seed = seeds[0]
    exact_key = ("exact", 1.0, "")
    sample_keys = [("sample", rate, str(seed)) for rate in rates]
    series = {key: {} for key in (exact_key, *sample_keys)}
    empty_samples = set()

    for row in rows:
        if row["question"] != "hours":
            continue
        if any(row[field] != manifest[field] for field in ("run_id", "dataset_id", "config_version")):
            raise ValueError("Rândurile de ore nu corespund manifestului rulării.")
        key = (row["method"], float(row["sample_rate"]), row["seed"])
        hour = row["group_key"]
        if key not in series or hour not in HOURS or hour in series[key]:
            raise ValueError(f"Grup de ore neașteptat sau duplicat: {key}, {hour}.")
        value = float(row["value"])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Număr de curse invalid pentru ora {hour}.")
        series[key][hour] = value
        if key[0] == "sample" and row["status"] == "empty_sample":
            empty_samples.add(key)

    if any(len(values) != len(HOURS) for values in series.values()):
        raise ValueError("Fiecare serie trebuie să conțină toate cele 24 de ore.")

    start = datetime.fromisoformat(manifest["period"]["start"]).date().isoformat()
    end = datetime.fromisoformat(manifest["period"]["end"]).date().isoformat()
    data_label = "Fixture · date de test" if manifest["data_kind"] == "fixture" else "NYC Yellow Taxi"
    subtitle = f"{data_label} · Perioadă [{start}, {end}) · Seed {seed}"

    def proportions(key):
        values = series[key]
        total = sum(values.values())
        return {hour: (100.0 * value / total if total else 0.0)
                for hour, value in values.items()}

    normalized = {key: proportions(key) for key in series}

    def title(key):
        suffix = " · eșantion gol" if key in empty_samples else ""
        error = (metric_values or {}).get(key[1])
        error_label = f" | Eroare pe ore față de exact: {error:.4%}" if error is not None else ""
        return f"Curse după ora zilei · eșantion {key[1]:.0%}{suffix}{error_label}<br><sup>{subtitle}</sup>"

    fig = go.Figure()
    fig.add_scatter(
        x=HOURS, y=[normalized[exact_key][hour] for hour in HOURS],
        name="Exact · 100%", mode="lines+markers", visible=True,
        line=dict(color="#204D87", width=3),
        hovertemplate="Ora %{x}:00<br>Exact: %{y:.2f}%<extra></extra>",
    )
    for index, key in enumerate(sample_keys):
        label = f"Estimat · {key[1]:.0%}" + (" (gol)" if key in empty_samples else "")
        fig.add_scatter(
            x=HOURS, y=[normalized[key][hour] for hour in HOURS],
            name=label, mode="lines+markers", visible=(index == 0),
            line=dict(color="#B94D18", width=2, dash="dash"),
            marker=dict(symbol="diamond"),
            hovertemplate="Ora %{x}:00<br>Estimat: %{y:.2f}%<extra></extra>",
        )

    buttons = [
        dict(label=f"{key[1]:.0%}", method="update",
             args=[{"visible": [True] + [other == key for other in sample_keys]},
                   {"title.text": title(key)}])
        for key in sample_keys
    ]
    fig.update_layout(
        title=dict(text=title(sample_keys[0]), x=0.03, xanchor="left"),
        template="plotly_white", margin=dict(t=120, b=65),
        xaxis=dict(title="Ora zilei", type="category", categoryorder="array",
                   categoryarray=HOURS, tickmode="array", tickvals=HOURS,
                   ticktext=[f"{hour}:00" for hour in HOURS], tickangle=-45),
        yaxis=dict(title="Proporția curselor (%)", range=[0, 100], ticksuffix="%"),
        legend=dict(x=0.01, y=0.98, xanchor="left", yanchor="top",
                    itemclick=False, itemdoubleclick=False),
        updatemenus=[dict(buttons=buttons, active=0, x=1, y=1.12,
                          xanchor="right", yanchor="bottom")],
        meta=dict(run_id=manifest["run_id"], period=dict(start=start, end=end), seed=seed),
    )
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Directorul rulării pilot")
    run_dir = parser.parse_args().run_dir
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    with (run_dir / "results.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    with (run_dir / "errors.csv").open(encoding="utf-8", newline="") as source:
        errors = list(csv.DictReader(source))
    from src.render import build_pilot_figures
    fig = build_pilot_figures(rows, manifest, errors)["hours"]

    output = run_dir / "hours.html"
    fig.write_html(output, include_plotlyjs=True, full_html=True)
    print(output.resolve())


if __name__ == "__main__":
    main()
