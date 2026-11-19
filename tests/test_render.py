from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from plotly.offline import get_plotlyjs

from src.benchmark import prepare_fixture, run_benchmark


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external_scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.external_scripts.extend(value for name, value in attrs if name == "src")


class RenderIntegrationTests(unittest.TestCase):
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
                for name in ("results.csv", "run_manifest.json"):
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
                                         ("distance.html", "Distance distribution")):
                with self.subTest(name=name):
                    html = (render_dir / name).read_text(encoding="utf-8")
                    scripts = ScriptSources()
                    scripts.feed(html)
                    scripts.close()
                    self.assertEqual(scripts.external_scripts, [])
                    _, inline_bundle, figure_html = html.partition(bundle)
                    self.assertTrue(inline_bundle, "Lipsește biblioteca Plotly inclusă în HTML.")
                    self.assertTrue("Plotly.newPlot(" in figure_html, "Lipsește graficul.")
                    self.assertTrue(expected_label in figure_html, "Graficul nu corespunde exportului.")
