import argparse
import csv
import json
import math
from pathlib import Path
import re

import pandas as pd

from src.config import DISTANCE_BINS, RUNS_DIR
from src.figures_hours import build_hours_figure
from src.metrics import evaluate
from src.plots import plot_distance_distribution


def load_pilot_run(run_dir):
    run_dir = Path(run_dir)
    with (run_dir / "run_manifest.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    if manifest["stage"] != "pilot" or manifest["status"] != "complete":
        raise ValueError("Selectează o rulare pilot completă.")
    identity = ("run_id", "dataset_id", "config_version")
    with (run_dir / "results.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != manifest["result_rows"]:
        raise ValueError("results.csv nu are numărul de rânduri din manifest.")
    if any(row[key] != manifest[key] for row in rows for key in identity):
        raise ValueError("results.csv nu corespunde manifestului rulării.")
    _read_errors(run_dir, manifest)
    return rows, manifest


def _read_errors(run_dir, manifest):
    identity = ("run_id", "dataset_id", "config_version")
    with (Path(run_dir) / "errors.csv").open(encoding="utf-8", newline="") as source:
        errors = list(csv.DictReader(source))
    if len(errors) != manifest["error_rows"]:
        raise ValueError("errors.csv nu are numărul de rânduri din manifest.")
    if any(row[key] != manifest[key] for row in errors for key in identity):
        raise ValueError("errors.csv nu corespunde manifestului rulării.")
    return errors


def _validate_errors(rows, errors, rates, seed):
    """Verifică metricile salvate față de cele recalculate din rezultatele pilotului."""
    if errors is None:
        return {}
    saved = {}
    for row in errors:
        if row["method"] != "sample" or int(row["seed"]) != int(seed):
            raise ValueError("Rând neașteptat în errors.csv.")
        key = (row["question"], float(row["sample_rate"]), row["metric"])
        if key in saved:
            raise ValueError(f"Rând de metrică duplicat: {key}")
        saved[key] = row

    exact_rows = {
        question: [(row["group_key"], float(row["value"])) for row in rows
                   if row["question"] == question and row["method"] == "exact"]
        for question in ("hours", "distance")
    }
    metric_config = {
        "hours": "normalized_absolute_error",
        "distance": "total_variation",
    }
    displayed = {"hours": {}, "distance": {}}
    for rate in rates:
        for question, metric_name in metric_config.items():
            sample_rows = [
                (row["group_key"], float(row["value"])) for row in rows
                if row["question"] == question and row["method"] == "sample"
                and float(row["sample_rate"]) == rate and int(row["seed"]) == int(seed)
            ]
            actual = evaluate(exact_rows[question], sample_rows, question)
            row = saved.get((question, rate, metric_name))
            if row is None or row["status"] != actual["status"]:
                raise ValueError(f"Valoare {metric_name} lipsă sau inconsistentă pentru {question} la {rate:g}.")
            recorded = None if row["value"] == "" else float(row["value"])
            if recorded is None:
                if actual["value"] is not None:
                    raise ValueError(f"Valoarea salvată {metric_name} nu corespunde cu results.csv.")
            elif actual["value"] is None or not math.isclose(
                    recorded, actual["value"], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"Valoarea salvată {metric_name} nu corespunde cu results.csv.")
            displayed[question][rate] = recorded
    return displayed


def build_pilot_figures(rows, manifest, errors=None):
    """Construiește graficele pilot și atașează erorile verificate față de numărătorile exacte."""
    rates = tuple(float(rate) for rate in manifest["protocol"]["sample_rates"])
    seed = manifest["protocol"]["seeds"][0]
    errors_by_question = _validate_errors(rows, errors, rates, seed)
    hour_metrics = errors_by_question.get("hours")
    if hour_metrics is None:
        hour_metrics = _calculate_metric_map(rows, "hours", rates)

    hours = build_hours_figure(rows, manifest, metric_values=hour_metrics)
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
            raise ValueError(f"Număr invalid de curse pentru intervalul {bin_id}.")
        series[key][bin_id] = value

    if any(set(values) != bins for values in series.values()):
        raise ValueError("Fiecare serie trebuie să conțină toate cele cinci intervale de distanță.")

    def frame(key):
        return pd.DataFrame(series[key].items(), columns=["group_key", "value"])

    samples = {key[1]: frame(key) for key in sample_keys}
    start = manifest["period"]["start"][:10]
    end = manifest["period"]["end"][:10]
    period = f"[{start}, {end})"
    if manifest["data_kind"] == "fixture":
        period = f"{period} · fixture de test"
    distance_metrics = errors_by_question.get("distance")
    if distance_metrics is None:
        distance_metrics = _calculate_metric_map(rows, "distance", rates)

    distance = plot_distance_distribution(
        frame(exact_key), samples[rates[0]], rates[0],
        analysis_period=period, random_seed=seed, sample_options=samples,
        metric_values=distance_metrics, metric_label="TVD față de exact",
    )
    return {"hours": hours, "distance": distance}


def _calculate_metric_map(rows, question, rates):
    exact_rows = [(row["group_key"], float(row["value"])) for row in rows
                  if row["question"] == question and row["method"] == "exact"]
    result = {}
    for rate in rates:
        estimates = [(row["group_key"], float(row["value"])) for row in rows
                     if row["question"] == question and row["method"] == "sample"
                     and float(row["sample_rate"]) == rate]
        metric = evaluate(exact_rows, estimates, question)
        result[rate] = metric["value"]
    return result


def render_pilot(run_dir):
    rows, manifest = load_pilot_run(run_dir)
    errors = _read_errors(run_dir, manifest)
    outputs = []
    for name, figure in build_pilot_figures(rows, manifest, errors).items():
        out = Path(run_dir) / f"{name}.html"
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
