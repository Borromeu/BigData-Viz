"""Generează grafice HTML offline pentru o rulare pilot completă."""

import argparse
import shutil

from src.config import RESULTS_DIR, RUNS_DIR
from src.render import render_pilot, validate_run_id


def main(run_id="pilot_01"):
    validate_run_id(run_id)
    run_dir = RUNS_DIR / run_id
    outputs = render_pilot(run_dir)
    distance = next(path for path in outputs if path.name == "distance.html")
    demo_copy = RESULTS_DIR / "distance_distribution_demo.html"
    shutil.copyfile(distance, demo_copy)
    return [*outputs, demo_copy]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="pilot_01")
    args = parser.parse_args()
    for result in main(args.run_id):
        print(result.resolve())
