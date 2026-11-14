from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import duckdb

from src.config import CONFIG_VERSION, FILTER_VERSION
from src.sampling import get_manifest_path, main, run_sampling_cli
from src.sampling_core import artifacts


def _mock_register_trips(
    con: duckdb.DuckDBPyConnection,
    files: tuple[Path, ...],
    start: datetime,
    end: datetime,
) -> None:
    paths = [str(Path(f).resolve()) for f in files]
    con.execute("SET VARIABLE mock_src = ?", [paths[0]])
    con.execute("SET VARIABLE mock_start = ?", [start.isoformat(sep=" ")])
    con.execute("SET VARIABLE mock_end = ?", [end.isoformat(sep=" ")])
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW trips AS
        SELECT
            CAST(tpep_pickup_datetime AS TIMESTAMP) AS pickup_at,
            CAST(trip_distance AS DOUBLE) AS distance_miles,
            COALESCE(CAST(PULocationID AS INTEGER), 0) AS pickup_zone
        FROM read_parquet(getvariable('mock_src'))
        WHERE tpep_pickup_datetime IS NOT NULL
          AND CAST(tpep_pickup_datetime AS TIMESTAMP) >= CAST(getvariable('mock_start') AS TIMESTAMP)
          AND CAST(tpep_pickup_datetime AS TIMESTAMP) < CAST(getvariable('mock_end') AS TIMESTAMP)
          AND trip_distance IS NOT NULL
          AND trip_distance > 0
        """
    )


class SamplingCliTests(unittest.TestCase):
    def _write_synthetic_tlc_parquet(self, target_path: Path) -> None:
        con = duckdb.connect()
        try:
            con.execute(
                """
                COPY (
                    SELECT
                        TIMESTAMP '2025-01-10 08:30:00' + INTERVAL (i) MINUTE AS tpep_pickup_datetime,
                        1.5 + (i % 10) AS trip_distance,
                        100 + (i % 5) AS PULocationID
                    FROM range(0, 200) t(i)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(target_path)],
            )
        finally:
            con.close()

    def test_cli_uses_src_data_register_trips_and_verifies_parquet_schema_and_rows(self) -> None:
        fake_data_module = types.ModuleType("src.data")
        fake_data_module.register_trips = _mock_register_trips  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_dir = tmp / "raw"
            samples_dir = tmp / "samples"
            raw_dir.mkdir()
            raw_parquet = raw_dir / "yellow_tripdata_2025-01.parquet"
            self._write_synthetic_tlc_parquet(raw_parquet)

            with mock.patch.dict(sys.modules, {"src.data": fake_data_module}):
                exit_code = main(
                    [
                        "--stage",
                        "pilot",
                        "--dataset",
                        "jan",
                        "--raw-dir",
                        str(raw_dir),
                        "--samples-dir",
                        str(samples_dir),
                    ]
                )
            self.assertEqual(exit_code, 0)

            expected = [
                (samples_dir / "jan_rate-0.01_seed-42.parquet", 0.01),
                (samples_dir / "jan_rate-0.1_seed-42.parquet", 0.10),
            ]
            con = duckdb.connect()
            try:
                for parquet_path, expected_rate in expected:
                    self.assertTrue(parquet_path.exists())
                    manifest = json.loads(
                        get_manifest_path(parquet_path).read_text(encoding="utf-8")
                    )
                    self.assertEqual(manifest["dataset_id"], "jan")
                    self.assertEqual(manifest["seed"], 42)
                    self.assertAlmostEqual(manifest["sample_rate"], expected_rate)
                    self.assertEqual(manifest["config_version"], CONFIG_VERSION)
                    self.assertEqual(manifest["filter_version"], FILTER_VERSION)

                    # Recitim Parquet-ul și verificăm schema, numărul de rânduri și eligibilitatea
                    con.execute("SET VARIABLE check_pq = ?", [str(parquet_path.resolve())])
                    cols = [
                        row[0]
                        for row in con.execute(
                            "DESCRIBE SELECT * FROM read_parquet(getvariable('check_pq'))"
                        ).fetchall()
                    ]
                    self.assertEqual(cols, ["pickup_at", "distance_miles", "pickup_zone"])

                    rows = con.execute(
                        "SELECT pickup_at, distance_miles, pickup_zone "
                        "FROM read_parquet(getvariable('check_pq'))"
                    ).fetchall()
                    self.assertEqual(len(rows), manifest["row_count"])
                    for pickup_at, distance_miles, pickup_zone in rows:
                        self.assertIsNotNone(pickup_at)
                        self.assertGreaterEqual(pickup_at, datetime(2025, 1, 1))
                        self.assertLess(pickup_at, datetime(2025, 2, 1))
                        self.assertGreater(distance_miles, 0.0)
                        self.assertIsNotNone(pickup_zone)
            finally:
                con.close()

    def test_cli_computes_source_hash_once_and_preserves_cost_on_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_dir = tmp / "raw"
            samples_dir = tmp / "samples"
            raw_dir.mkdir()
            raw_parquet = raw_dir / "yellow_tripdata_2025-01.parquet"
            self._write_synthetic_tlc_parquet(raw_parquet)

            real_sha256 = artifacts.compute_file_sha256
            raw_hash_calls = 0

            def counting_sha256(file_path: str | Path) -> str:
                nonlocal raw_hash_calls
                if Path(file_path).resolve() == raw_parquet.resolve():
                    raw_hash_calls += 1
                return real_sha256(file_path)

            with mock.patch.object(artifacts, "compute_file_sha256", side_effect=counting_sha256):
                first_run = run_sampling_cli(
                    stage="pilot",
                    dataset="jan",
                    raw_dir=raw_dir,
                    samples_dir=samples_dir,
                    register_trips_fn=_mock_register_trips,
                )
            # Hash-ul fișierului brut este calculat o singură dată pentru ambele rate (1% și 10%)
            self.assertEqual(raw_hash_calls, 1)
            self.assertTrue(all(not item["reused"] for item in first_run))

            second_run = run_sampling_cli(
                stage="pilot",
                dataset="jan",
                raw_dir=raw_dir,
                samples_dir=samples_dir,
                register_trips_fn=_mock_register_trips,
            )
            self.assertTrue(all(item["reused"] for item in second_run))
            for first_item, second_item in zip(first_run, second_run, strict=True):
                self.assertEqual(second_item["build_seconds"], first_item["build_seconds"])

    def test_cli_fails_explicitly_without_fallback_when_src_data_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_dir = tmp / "raw"
            raw_dir.mkdir()
            raw_parquet = raw_dir / "yellow_tripdata_2025-01.parquet"
            self._write_synthetic_tlc_parquet(raw_parquet)

            with mock.patch.dict(sys.modules, {"src.data": None}):
                exit_code = main(
                    [
                        "--stage",
                        "pilot",
                        "--dataset",
                        "jan",
                        "--raw-dir",
                        str(raw_dir),
                        "--samples-dir",
                        str(tmp / "samples"),
                    ]
                )
            self.assertNotEqual(exit_code, 0)

    def test_cli_missing_data_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            empty_raw = tmp / "empty_raw"
            empty_raw.mkdir()
            exit_code = main(
                [
                    "--stage",
                    "pilot",
                    "--dataset",
                    "jan",
                    "--raw-dir",
                    str(empty_raw),
                    "--samples-dir",
                    str(tmp / "samples"),
                ]
            )
            self.assertNotEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
