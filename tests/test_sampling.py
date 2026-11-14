from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import duckdb
import pandas as pd

from src.metrics import evaluate
from src.queries import query_counts
from src.sampling import (
    build_sample,
    build_sample_view,
    check_sample_reuse,
    estimate_counts,
    format_sample_results,
    get_manifest_path,
    materialize_sample_table,
    register_sample_parquet,
    sample_and_query,
)


class SamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = duckdb.connect()
        fixture = (Path(__file__).parent / "fixtures" / "trips.csv").as_posix()
        self.con.execute(
            f"""
            CREATE TABLE trips AS
            SELECT tpep_pickup_datetime AS pickup_at,
                   trip_distance AS distance_miles,
                   PULocationID AS pickup_zone,
                   fixture_id
            FROM read_csv_auto('{fixture}')
            WHERE fixture_id BETWEEN 1 AND 12
            """
        )

    def tearDown(self) -> None:
        self.con.close()

    def test_invalid_probabilities_rejected(self) -> None:
        for bad_p in (0, -0.1, 1.01, float("nan"), float("inf"), float("-inf"), True, False, "0.1"):
            with self.subTest(p=bad_p):
                with self.assertRaises(ValueError):
                    estimate_counts([("00", 2)], bad_p)
                with self.assertRaises(ValueError):
                    build_sample_view(self.con, sample_rate=bad_p)

    def test_invalid_seeds_rejected_before_changing_threads(self) -> None:
        self.con.execute("SET threads = 4")
        for bad_seed in (True, False, 1.5, "42", -1, 4_294_967_296):
            with self.subTest(seed=bad_seed):
                with self.assertRaises(ValueError):
                    build_sample_view(self.con, seed=bad_seed)
                threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
                self.assertEqual(threads, 4)

    def test_disallowed_source_rejected_before_changing_threads(self) -> None:
        self.con.execute("SET threads = 4")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "out.parquet"
            for bad_source in ("trips; DROP TABLE trips", "unknown_view", "sample_trips"):
                with self.subTest(source=bad_source):
                    with self.assertRaises(ValueError):
                        build_sample(self.con, 0.5, 42, out_file, source_view=bad_source)
                    threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
                    self.assertEqual(threads, 4)

    def test_sampling_p_equals_one_returns_all_eligible_rows(self) -> None:
        materialize_sample_table(self.con, p=1.0, seed=42)
        count = int(self.con.execute("SELECT COUNT(*) FROM sample_trips").fetchone()[0])
        self.assertEqual(count, 12)

    def test_same_inputs_and_seed_reproduce_multiset(self) -> None:
        materialize_sample_table(self.con, p=0.5, seed=42)
        rows_a = Counter(self.con.execute("SELECT * FROM sample_trips").fetchall())

        materialize_sample_table(self.con, p=0.5, seed=42)
        rows_b = Counter(self.con.execute("SELECT * FROM sample_trips").fetchall())

        self.assertEqual(rows_a, rows_b)

    def test_empty_source_produces_valid_empty_sample_and_manifest(self) -> None:
        self.con.execute("CREATE OR REPLACE TABLE trips AS SELECT * FROM trips WHERE false")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "empty.parquet"
            duration = build_sample(self.con, 0.1, 42, out_file)
            self.assertGreaterEqual(duration, 0.0)
            self.assertTrue(out_file.exists())

            manifest = json.loads(get_manifest_path(out_file).read_text(encoding="utf-8"))
            self.assertEqual(manifest["row_count"], 0)
            self.assertEqual(manifest["method"], "bernoulli")

            register_sample_parquet(self.con, out_file)
            raw = query_counts(self.con, "hours", "sample_trips")
            estimated = estimate_counts(raw, 0.1)
            self.assertEqual(len(estimated), 24)
            self.assertTrue(all(v == 0.0 for _, v in estimated))

            formatted = format_sample_results(
                estimated,
                run_id="r1",
                dataset_id="jan",
                question="hours",
                sample_rate=0.1,
                seed=42,
            )
            self.assertTrue(all(row["status"] == "empty_sample" for row in formatted))

    def test_threads_restored_on_success_and_on_error(self) -> None:
        self.con.execute("SET threads = 4")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "ok.parquet"
            build_sample(self.con, 0.5, 42, out_file)
            threads_after_ok = int(
                self.con.execute("SELECT current_setting('threads')").fetchone()[0]
            )
            self.assertEqual(threads_after_ok, 4)

            bad_out = Path(tmpdir) / "as_dir.parquet"
            bad_out.mkdir()
            with self.assertRaises(Exception):
                build_sample(self.con, 0.5, 42, bad_out)
            threads_after_err = int(
                self.con.execute("SELECT current_setting('threads')").fetchone()[0]
            )
            self.assertEqual(threads_after_err, 4)

    def test_build_sample_requires_output_path(self) -> None:
        self.con.execute("SET threads = 4")
        with self.assertRaises(ValueError):
            build_sample(self.con, 0.1, 42)
        threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
        self.assertEqual(threads, 4)

    def test_estimate_counts_pairs_and_validation_consistency(self) -> None:
        self.assertEqual(
            estimate_counts([("00", 2), ("01", 3)], 0.1),
            [("00", 20.0), ("01", 30.0)],
        )

        with self.assertRaises(ValueError):
            estimate_counts(pd.DataFrame({"group_key": ["00"], "value": [True]}), 0.1)
        with self.assertRaises(ValueError):
            estimate_counts(pd.DataFrame({"group_key": ["00"], "value": ["2"]}), 0.1)
        with self.assertRaises(ValueError):
            estimate_counts([("00", "2")], 0.1)

        with self.assertRaises(ValueError):
            estimate_counts([1], 5e-324)

    def test_end_to_end_query_estimator_and_evaluate(self) -> None:
        exact_rows = query_counts(self.con, "distance", "trips").fetchall()
        estimated_rows = sample_and_query(
            self.con,
            question="distance",
            sample_rate=1.0,
            seed=42,
            source_view="trips",
        )
        self.assertEqual(len(estimated_rows), 5)
        eval_res = evaluate(exact_rows, estimated_rows, "distance")
        self.assertEqual(eval_res["status"], "ok")
        self.assertAlmostEqual(eval_res["value"], 0.0)

    def test_export_parquet_and_path_with_apostrophe_and_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tricky_dir = Path(tmpdir) / "Stefan's dir with spaces"
            out_file = tricky_dir / "sample's_test.parquet"
            duration = build_sample(self.con, 1.0, 42, out_file)
            self.assertGreater(duration, 0.0)
            self.assertTrue(out_file.exists())

            rows = self.con.execute(
                "SELECT pickup_at, distance_miles, pickup_zone FROM read_parquet(?)",
                [str(out_file)],
            ).fetchall()
            self.assertEqual(len(rows), 12)

    def test_manifest_reuse_and_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_file = tmp / "yellow_tripdata_2025-01.parquet"
            self.con.execute("COPY (SELECT * FROM trips) TO ? (FORMAT PARQUET)", [str(raw_file)])

            out_file = tmp / "jan_rate-0.5_seed-42.parquet"
            period = (datetime(2025, 1, 1), datetime(2025, 2, 1))
            build_sample(
                self.con,
                0.5,
                42,
                out_file,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
            )

            ok, _ = check_sample_reuse(
                out_file,
                p=0.5,
                seed=42,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
            )
            self.assertTrue(ok)

            reused_duration = build_sample(
                self.con,
                0.5,
                42,
                out_file,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
                reuse=True,
            )
            self.assertEqual(reused_duration, 0.0)

            ok_diff_filter, _ = check_sample_reuse(
                out_file,
                p=0.5,
                seed=42,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
                filter_version="2",
            )
            self.assertFalse(ok_diff_filter)
            with self.assertRaises(ValueError):
                build_sample(
                    self.con,
                    0.5,
                    42,
                    out_file,
                    dataset_id="jan",
                    period=period,
                    source_files=[raw_file],
                    filter_version="2",
                    reuse=True,
                )

            raw_file.write_bytes(raw_file.read_bytes() + b"tamper")
            ok_diff_hash, _ = check_sample_reuse(
                out_file,
                p=0.5,
                seed=42,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
            )
            self.assertFalse(ok_diff_hash)

    def test_cli_pilot_jan_generates_two_samples_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_dir = tmp / "raw"
            samples_dir = tmp / "samples"
            raw_dir.mkdir()

            raw_parquet = raw_dir / "yellow_tripdata_2025-01.parquet"
            self.con.execute(
                """
                COPY (
                    SELECT
                        TIMESTAMP '2025-01-10 08:30:00' + INTERVAL (i) MINUTE AS tpep_pickup_datetime,
                        1.5 + (i % 10) AS trip_distance,
                        100 + (i % 5) AS PULocationID
                    FROM range(0, 200) t(i)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(raw_parquet)],
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "src.sampling",
                    "--stage",
                    "pilot",
                    "--dataset",
                    "jan",
                    "--raw-dir",
                    str(raw_dir),
                    "--samples-dir",
                    str(samples_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            expected_files = [
                samples_dir / "jan_rate-0.01_seed-42.parquet",
                samples_dir / "jan_rate-0.1_seed-42.parquet",
            ]
            for parquet_path in expected_files:
                self.assertTrue(parquet_path.exists(), msg=f"Missing {parquet_path}")
                manifest_path = get_manifest_path(parquet_path)
                self.assertTrue(manifest_path.exists(), msg=f"Missing {manifest_path}")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["dataset_id"], "jan")
                self.assertEqual(manifest["seed"], 42)
                self.assertEqual(manifest["method"], "bernoulli")

    def test_cli_missing_data_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            empty_raw = tmp / "empty_raw"
            empty_raw.mkdir()
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "src.sampling",
                    "--stage",
                    "pilot",
                    "--dataset",
                    "jan",
                    "--raw-dir",
                    str(empty_raw),
                    "--samples-dir",
                    str(tmp / "samples"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Missing required raw dataset", proc.stderr)


if __name__ == "__main__":
    unittest.main()