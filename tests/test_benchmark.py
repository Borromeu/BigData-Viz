import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from src import benchmark
from src.sampling import estimate_counts, get_manifest_path, register_sample_parquet


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class BenchmarkProtocolTests(unittest.TestCase):
    def test_pilot_has_six_cases_without_duplicate_exact(self):
        cases = benchmark.pilot_cases()
        self.assertEqual(len(cases), 6)
        self.assertEqual(len(set(cases)), 6)
        self.assertEqual(sum(case.method == "exact" for case in cases), 2)
        self.assertEqual({case.seed for case in cases if case.method == "sample"}, {42})

    def test_measure_includes_lazy_execution_and_fetch_but_not_estimation(self):
        events = []
        ticks = iter([10.0, 10.25])

        def clock():
            events.append("clock")
            return next(ticks)

        class Relation:
            def fetchall(self):
                events.append("fetchall")
                return [("00", 2)]

        def query(*args):
            events.append("query")
            return Relation()

        with patch.object(benchmark, "query_counts", side_effect=query), \
             patch.object(benchmark, "estimate_counts") as estimate:
            rows, elapsed = benchmark.measure_query(None, benchmark.BenchmarkCase("hours"), clock=clock)
        self.assertEqual(events, ["clock", "query", "fetchall", "clock"])
        self.assertEqual(rows, [("00", 2)])
        self.assertEqual(elapsed, 0.25)
        estimate.assert_not_called()


class BenchmarkIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.samples = self.root / "samples"
        self.runs = self.root / "runs"
        self.dataset, self.source_manifest = benchmark.prepare_fixture(self.samples)

    def run_pilot(self, run_id="test_pilot"):
        return benchmark.run_benchmark(
            self.dataset, run_id=run_id, samples_dir=self.samples,
            runs_dir=self.runs, source_manifest=self.source_manifest,
        )

    def test_real_modules_produce_complete_matrix_and_correct_estimates(self):
        # Spy pe execuțiile reale: 6 încălziri + 18 măsurători, fără SQL copiat.
        with patch.object(benchmark, "query_counts", wraps=benchmark.query_counts) as query:
            run_dir = self.run_pilot()
        self.assertEqual(query.call_count, 24)
        timings = read_csv(run_dir / "timings.csv")
        results = read_csv(run_dir / "results.csv")
        errors = read_csv(run_dir / "errors.csv")
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        self.assertEqual((len(timings), len(results), len(errors)), (18, 87, 4))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["data_kind"], "fixture")
        self.assertEqual(manifest["measured_queries"], 18)
        self.assertEqual({r["repeat"] for r in timings}, {"1", "2", "3"})
        self.assertTrue(all(float(row["elapsed_seconds"]) > 0 for row in timings))
        self.assertEqual([r["method"] for r in timings[:3]], ["exact", "sample", "sample"])
        first_round = [(r["question"], r["method"], r["sample_rate"]) for r in timings[:6]]
        second_round = [(r["question"], r["method"], r["sample_rate"]) for r in timings[6:12]]
        self.assertEqual(first_round, list(reversed(second_round)))

        expected = json.loads((benchmark.PROJECT_ROOT / "tests/fixtures/expected.json").read_text())
        for question in ("hours", "distance"):
            exact = {r["group_key"]: float(r["value"]) for r in results
                     if r["question"] == question and r["method"] == "exact"}
            self.assertEqual(exact, expected["exact"][question])
            self.assertTrue(all(r["seed"] == "" for r in results if r["method"] == "exact"))

        # Estimările exportate sunt chiar count/p, folosind Parquet-urile pregătite.
        con = duckdb.connect()
        try:
            for sample in manifest["samples"]:
                rate = sample["metadata"]["sample_rate"]
                register_sample_parquet(con, sample["path"])
                for question in ("hours", "distance"):
                    raw = benchmark.query_counts(con, question, "sample_trips").fetchall()
                    exported = {r["group_key"]: float(r["value"]) for r in results
                                if r["question"] == question and r["method"] == "sample"
                                and float(r["sample_rate"]) == rate}
                    self.assertEqual(exported, dict(estimate_counts(raw, rate)))
                    if sum(value for _, value in raw) == 0:
                        error = next(r for r in errors if r["question"] == question
                                     and float(r["sample_rate"]) == rate)
                        self.assertEqual(error["status"], "empty_sample")
                        if question == "distance":
                            self.assertEqual(error["value"], "")
        finally:
            con.close()

    def test_existing_run_is_not_overwritten(self):
        run_dir = self.run_pilot()
        before = {p.name: p.read_bytes() for p in run_dir.iterdir()}
        with self.assertRaises(FileExistsError):
            self.run_pilot()
        self.assertEqual(before, {p.name: p.read_bytes() for p in run_dir.iterdir()})

    def test_missing_sample_stops_before_measurement_without_regeneration(self):
        path = next(self.samples.glob("*.parquet"))
        path.unlink()
        with patch.object(benchmark, "measure_query") as measure, \
             patch.object(benchmark, "build_sample") as build:
            with self.assertRaisesRegex(ValueError, "lipsă sau incompatibil"):
                self.run_pilot()
        measure.assert_not_called()
        build.assert_not_called()
        self.assertFalse(self.runs.exists())

    def test_wrong_sample_identity_is_rejected(self):
        path = get_manifest_path(next(self.samples.glob("*.parquet")))
        data = json.loads(path.read_text())
        data["seed"] = 43
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "lipsă sau incompatibil"):
            self.run_pilot()

    def test_incorrect_row_count_in_sample_manifest_is_rejected(self):
        path = get_manifest_path(next(self.samples.glob("*.parquet")))
        data = json.loads(path.read_text())
        data["row_count"] += 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Număr de rânduri"):
            self.run_pilot()

    def test_source_hash_mismatch_is_rejected_before_measurement(self):
        data = json.loads(self.source_manifest.read_text())
        data["files"][0]["sha256"] = "0" * 64
        self.source_manifest.write_text(json.dumps(data))
        with patch.object(benchmark, "measure_query") as measure:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                self.run_pilot()
        measure.assert_not_called()

    def test_mid_run_failure_preserves_partial_timings_and_incomplete_manifest(self):
        real_measure = benchmark.measure_query
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated execution failure")
            return real_measure(*args)

        with patch.object(benchmark, "measure_query", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                self.run_pilot()
        run_dir = self.runs / "test_pilot"
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        self.assertEqual(manifest["status"], "incomplete")
        self.assertEqual(len(read_csv(run_dir / "timings.csv")), 1)
        self.assertFalse((run_dir / "results.csv").exists())

    def test_changed_result_between_repetitions_is_rejected(self):
        with patch.object(benchmark, "measure_query", return_value=([("00", 999)], 0.1)):
            with self.assertRaisesRegex(RuntimeError, "Rezultate diferite"):
                self.run_pilot()

    def test_run_id_cannot_escape_results_directory(self):
        with self.assertRaises(ValueError):
            self.run_pilot("../elsewhere")


if __name__ == "__main__":
    unittest.main()