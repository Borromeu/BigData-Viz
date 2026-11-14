from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import duckdb

from src.metrics import evaluate
from src.queries import query_counts
from src.sampling import (
    materialize_sample_table,
    register_sample_parquet,
    sample_and_query,
)
from src.sampling_core import engine


class SamplingEngineTests(unittest.TestCase):
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

    def test_invalid_seeds_rejected_before_changing_threads(self) -> None:
        self.con.execute("SET threads = 4")
        for bad_seed in (True, False, 1.5, "42", -1, 4_294_967_296):
            with self.subTest(seed=bad_seed):
                with self.assertRaises(ValueError):
                    materialize_sample_table(self.con, p=0.5, seed=bad_seed)
                threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
                self.assertEqual(threads, 4)

    def test_disallowed_source_rejected_before_changing_threads(self) -> None:
        self.con.execute("SET threads = 4")
        for bad_source in ("trips; DROP TABLE trips", "unknown_view", "sample_trips"):
            with self.subTest(source=bad_source):
                with self.assertRaises(ValueError):
                    materialize_sample_table(self.con, p=0.5, seed=42, source_view=bad_source)
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

    def test_threads_changed_to_one_and_restored_after_sql_execution_error(self) -> None:
        self.con.execute("SET threads = 4")
        observed_threads_during_exec: list[int] = []
        original_set_threads = engine.set_threads

        def spy_set_threads(con: duckdb.DuckDBPyConnection, threads: int) -> None:
            original_set_threads(con, threads)
            observed_threads_during_exec.append(
                int(con.execute("SELECT current_setting('threads')").fetchone()[0])
            )

        # Ștergem tabelul trips astfel încât eroarea să apară în interiorul con.execute(sql),
        # DUPĂ ce threads a fost comutat la 1.
        self.con.execute("DROP TABLE trips")
        with mock.patch.object(engine, "set_threads", side_effect=spy_set_threads):
            with self.assertRaises(duckdb.Error):
                materialize_sample_table(self.con, p=0.5, seed=42)

        self.assertEqual(observed_threads_during_exec, [1, 4])
        final_threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
        self.assertEqual(final_threads, 4)

    def test_end_to_end_query_estimator_and_evaluate_with_non_unit_probability(self) -> None:
        exact_rows = query_counts(self.con, "distance", "trips").fetchall()

        # Materializăm determinist un eșantion de 4 rânduri (p = 1/3) pentru a verifica
        # că ponderarea 1/p se aplică exact o singură dată pe traseul comun.
        def deterministic_subset(
            con: duckdb.DuckDBPyConnection,
            p: float = 0.10,
            seed: int = 42,
            source_view: str = "trips",
        ) -> float:
            con.execute(
                "CREATE OR REPLACE TEMP TABLE sample_trips AS "
                "SELECT * FROM trips WHERE fixture_id IN (1, 3, 6, 9)"
            )
            return 0.001

        with mock.patch("src.sampling.materialize_sample_table", side_effect=deterministic_subset):
            estimated_rows = sample_and_query(
                self.con,
                question="distance",
                sample_rate=1 / 3,
                seed=42,
                source_view="trips",
            )

        self.assertEqual(
            estimated_rows,
            [("0", 3.0), ("1", 3.0), ("2", 3.0), ("3", 3.0), ("4", 0.0)],
        )
        eval_res = evaluate(exact_rows, estimated_rows, "distance")
        self.assertEqual(eval_res["status"], "ok")
        self.assertAlmostEqual(eval_res["value"], 0.25)

    def test_register_sample_parquet_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nonexistent.parquet"
            with self.assertRaises(FileNotFoundError):
                register_sample_parquet(self.con, missing)


if __name__ == "__main__":
    unittest.main()
