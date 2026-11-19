"""Exportă graficele pilot din fișierele unei rulări A3."""

import argparse
import csv
import json
import math
from pathlib import Path
import re

import pandas as pd

from src.config import DISTANCE_BINS, RUNS_DIR
from src.figures_hours import build_hours_figure
from src.plots import plot_distance_distribution


def load_pilot_run(run_dir):
    run_dir = Path(run_dir)
    with (run_dir / "run_manifest.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    if manifest["stage"] != "pilot" or manifest["status"] != "complete":
        raise ValueError("Selectează o rulare pilot completă.")
    with (run_dir / "results.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != manifest["result_rows"]:
        raise ValueError("results.csv nu are numărul de rânduri din manifest.")
    identity = ("run_id", "dataset_id", "config_version")
    if any(row[key] != manifest[key] for row in rows for key in identity):
        raise ValueError("results.csv nu corespunde manifestului rulării.")
    return rows, manifest


def build_pilot_figures(rows, manifest):
    """Primește numărătorile deja estimate de A3 și reconstruiește ambele grafice."""
    hours = build_hours_figure(rows, manifest)
    rates = tuple(float(rate) for rate in manifest["protocol"]["sample_rates"])
    seed = manifest["protocol"]["seeds"][0]
    exact_key = ("exact", 1.0, "")
    sample_keys = [("sample", rate, str(seed)) for rate in rates]
    series = {key: {} for key in (exact_key, *sample_keys)}
    bins = {str(bin_id) for bin_id, *_ in DISTANCE_BINS}

    for row in rows:
        if row["question"] != "distance":
            continue
        key = (row["method"], float(row["sample_rate"]), row["seed"])
        bin_id = row["group_key"]
        if key not in series or bin_id not in bins or bin_id in series[key]:
            raise ValueError(f"Interval de distanță neașteptat sau duplicat: {key}, {bin_id}.")
        value = float(row["value"])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Număr de curse invalid pentru intervalul {bin_id}.")
        series[key][bin_id] = value

    if any(set(values) != bins for values in series.values()):
        raise ValueError("Fiecare serie trebuie să conțină toate intervalele de distanță.")

    def frame(key):
        return pd.DataFrame(series[key].items(), columns=["group_key", "value"])

    samples = {key[1]: frame(key) for key in sample_keys}
    start = manifest["period"]["start"][:10]
    end = manifest["period"]["end"][:10]
    period = f"[{start}, {end})"
    if manifest["data_kind"] == "fixture":
        period = f"{period} · fixture de test"
    distance = plot_distance_distribution(
        frame(exact_key), samples[rates[0]], rates[0],
        analysis_period=period, random_seed=seed, sample_options=samples,
    )
    return {"hours": hours, "distance": distance}


def render_pilot(run_dir):
    run_dir = Path(run_dir)
    rows, manifest = load_pilot_run(run_dir)
    outputs = []
    for name, figure in build_pilot_figures(rows, manifest).items():
        out = run_dir / f"{name}.html"
        figure.write_html(out, include_plotlyjs=True, full_html=True)
        outputs.append(out)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="De exemplu pilot_01")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.run_id):
        parser.error("--run-id invalid")

    try:
        outputs = render_pilot(args.runs_dir / args.run_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"[Render] {exc}\n")
    for path in outputs:
        print(path.resolve())


if __name__ == "__main__":
    main()
