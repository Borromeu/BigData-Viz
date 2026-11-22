from html.parser import HTMLParser
import csv
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from plotly.offline import get_plotlyjs

from src.benchmark import prepare_fixture, run_benchmark
from src.render import _validate_errors, load_pilot_artifacts


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external_scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.external_scripts.extend(value for name, value in attrs if name == "src")


class RenderIntegrationTests(unittest.TestCase):
    def test_unexpected_error_key_is_rejected(self):
        errors = [{
            "method": "sample", "seed": "42", "question": "unexpected",
            "sample_rate": "0.01", "metric": "stale_metric",
            "value": "0.0", "status": "ok",
        }]
        with self.assertRaisesRegex(ValueError, "Chei neașteptate în errors.csv"):
            _validate_errors([], errors, (0.01, 0.1), 42)

    def test_render_cli_exports_two_self_contained_figures(self):
        run_id = "fixture_render"
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as render_temp:
            runs_dir = Path(render_temp)
            render_dir = runs_dir / run_id
            render_dir.mkdir()

            with tempfile.TemporaryDirectory() as benchmark_temp:
                benchmark_root = Path(benchmark_temp)
                samples_dir = benchmark_root / "samples"
                dataset, source_manifest = prepare_fixture(samples_dir)
                run_dir = run_benchmark(
                    dataset, run_id=run_id, samples_dir=samples_dir,
                    runs_dir=benchmark_root / "runs", source_manifest=source_manifest,
                )
                for name in ("results.csv", "run_manifest.json", "errors.csv"):
                    shutil.copyfile(run_dir / name, render_dir / name)

            result = subprocess.run(
                [sys.executable, "-m", "src.render", "--run-id", run_id,
                 "--runs-dir", str(runs_dir)],
                cwd=project_root, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {path.name for path in render_dir.glob("*.html")},
                {"hours.html", "distance.html"},
            )

            bundle = get_plotlyjs()
            for name, expected_label in (("hours.html", "00:00"),
                                         ("distance.html", "Distribuția distanțelor")):
                with self.subTest(name=name):
                    html = (render_dir / name).read_text(encoding="utf-8")
                    scripts = ScriptSources()
                    scripts.feed(html)
                    scripts.close()
                    self.assertEqual(scripts.external_scripts, [])
                    _, inline_bundle, figure_html = html.partition(bundle)
                    self.assertTrue(inline_bundle, "Lipsește biblioteca Plotly inclusă în HTML.")
                    self.assertTrue("Plotly.newPlot(" in figure_html, "Lipsește graficul.")
                    expected_html_label = expected_label.encode("unicode_escape").decode("ascii")
                    self.assertIn(expected_html_label, figure_html, "Graficul nu corespunde exportului.")
                    self.assertIn("1%", figure_html)
                    self.assertIn("10%", figure_html)
                    self.assertIn("Propor\\u021bia curselor (%)", figure_html)
                    if name == "hours.html":
                        metric_label = "Eroare normalizată pe numărul de curse"
                        self.assertIn(metric_label.encode("unicode_escape").decode("ascii"), figure_html)
                    else:
                        self.assertIn("TVD fa\\u021b\\u0103 de exact", figure_html)

            loaded_rows, loaded_manifest, _ = load_pilot_artifacts(render_dir)
            self.assertEqual(len(loaded_rows), loaded_manifest["result_rows"])
            errors_path = render_dir / "errors.csv"
            with errors_path.open(encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                fieldnames = reader.fieldnames
                errors = list(reader)
            original = errors[0]["value"]
            errors[0]["value"] = str(float(original or 0) + 0.123456789)
            with errors_path.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(errors)
            with self.assertRaisesRegex(ValueError, "Valoarea salvată"):
                load_pilot_artifacts(render_dir)
