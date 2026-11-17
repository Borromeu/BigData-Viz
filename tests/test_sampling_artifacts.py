from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import duckdb

from src.queries import query_counts
from src.sampling import (
    build_sample,
    check_sample_reuse,
    estimate_counts,
    format_sample_results,
    get_manifest_path,
    register_sample_parquet,
)
from src.sampling_core import artifacts


class SamplingArtifactsTests(unittest.TestCase):
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

    def test_overwrite_publication_failure_restores_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "sample.parquet"

            # Construim esantionul original si manifestul sau.
            build_sample(self.con, 0.5, 42, out_file)
            manifest_file = get_manifest_path(out_file)

            original_parquet = out_file.read_bytes()
            original_manifest = manifest_file.read_bytes()

            # Pastram functia reala pentru operatiile care trebuie sa reuseasca.
            original_replace = Path.replace

            def fail_manifest_replace(source: Path, target: Path) -> Path:
                # Simulam eroarea la publicarea noului manifest,
                # dupa ce noul Parquet a fost deja publicat.
                if (
                    source.name == manifest_file.name
                    and source.parent != manifest_file.parent
                    and Path(target) == manifest_file
                ):
                    raise OSError("Simulated manifest publication failure")

                return original_replace(source, target)

            with mock.patch.object(
                Path,
                "replace",
                new=fail_manifest_replace,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "Simulated manifest publication failure",
                ):
                    build_sample(
                        self.con,
                        0.5,
                        42,
                        out_file,
                        overwrite=True,
                    )

            # Ambele fisiere originale trebuie sa fie restaurate.
            self.assertTrue(out_file.exists())
            self.assertTrue(manifest_file.exists())

            self.assertEqual(out_file.read_bytes(), original_parquet)
            self.assertEqual(manifest_file.read_bytes(), original_manifest)

    def tearDown(self) -> None:
        self.con.close()

    def test_build_sample_requires_output_path_before_changing_threads(self) -> None:
        self.con.execute("SET threads = 4")
        with self.assertRaises(ValueError):
            build_sample(self.con, 0.1, 42)
        threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
        self.assertEqual(threads, 4)

    def test_threads_restored_after_export_execution_error(self) -> None:
        self.con.execute("SET threads = 4")
        observed_threads: list[int] = []
        original_set_threads = artifacts.set_threads

        def spy_set_threads(con: duckdb.DuckDBPyConnection, threads: int) -> None:
            original_set_threads(con, threads)
            observed_threads.append(
                int(con.execute("SELECT current_setting('threads')").fetchone()[0])
            )

        self.con.execute("DROP TABLE trips")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "fail.parquet"
            with mock.patch.object(artifacts, "set_threads", side_effect=spy_set_threads):
                with self.assertRaises(duckdb.Error):
                    build_sample(self.con, 0.5, 42, out_file)

        self.assertEqual(observed_threads, [1, 4])
        final_threads = int(self.con.execute("SELECT current_setting('threads')").fetchone()[0])
        self.assertEqual(final_threads, 4)

    def test_export_parquet_with_apostrophe_and_spaces_and_effective_memory_limit(self) -> None:
        self.con.execute("SET memory_limit = '512MB'")
        expected_mem = str(
            self.con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tricky_dir = Path(tmpdir) / "Stefan's dir with spaces"
            out_file = tricky_dir / "sample's_test.parquet"
            result = build_sample(self.con, 1.0, 42, out_file)
            self.assertFalse(result.reused)
            self.assertGreaterEqual(result.build_seconds, 0.0)
            self.assertTrue(out_file.exists())

            manifest = json.loads(get_manifest_path(out_file).read_text(encoding="utf-8"))
            self.assertEqual(manifest["settings"]["memory_limit"], expected_mem)
            self.assertEqual(manifest["row_count"], 12)

            rows = self.con.execute(
                "SELECT pickup_at, distance_miles, pickup_zone FROM read_parquet(?)",
                [str(out_file)],
            ).fetchall()
            self.assertEqual(len(rows), 12)

    def test_empty_source_produces_valid_empty_sample_and_manifest(self) -> None:
        self.con.execute("CREATE OR REPLACE TABLE trips AS SELECT * FROM trips WHERE false")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "empty.parquet"
            result = build_sample(self.con, 0.1, 42, out_file)
            self.assertEqual(result.row_count, 0)
            self.assertTrue(out_file.exists())

            register_sample_parquet(self.con, out_file)
            raw = query_counts(self.con, "hours", "sample_trips")
            estimated = estimate_counts(raw, 0.1)
            formatted = format_sample_results(
                estimated,
                run_id="r1",
                dataset_id="jan",
                question="hours",
                sample_rate=0.1,
                seed=42,
            )
            self.assertTrue(all(row["status"] == "empty_sample" for row in formatted))

    def test_manifest_reuse_preserves_original_build_seconds_and_invalidates_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_file = tmp / "yellow_tripdata_2025-01.parquet"
            self.con.execute("COPY (SELECT * FROM trips) TO ? (FORMAT PARQUET)", [str(raw_file)])

            out_file = tmp / "jan_rate-0.5_seed-42.parquet"
            period = (datetime(2025, 1, 1), datetime(2025, 2, 1))
            first = build_sample(
                self.con,
                0.5,
                42,
                out_file,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
            )
            self.assertFalse(first.reused)
            self.assertGreater(first.build_seconds, 0.0)

            reused_res = build_sample(
                self.con,
                0.5,
                42,
                out_file,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
                reuse=True,
            )
            self.assertTrue(reused_res.reused)
            self.assertEqual(reused_res.build_seconds, first.build_seconds)

            # Schimbarea filter_version invalidează reutilizarea
            ok_diff_filter, _ = check_sample_reuse(
                out_file,
                p=0.5,
                seed=42,
                con=self.con,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
                filter_version="2",
            )
            self.assertFalse(ok_diff_filter)

            # Schimbarea memory_limit pe conexiune invalidează reutilizarea
            other_con = duckdb.connect()
            try:
                other_con.execute("SET memory_limit = '256MB'")
                ok_diff_mem, _ = check_sample_reuse(
                    out_file,
                    p=0.5,
                    seed=42,
                    con=other_con,
                    dataset_id="jan",
                    period=period,
                    source_files=[raw_file],
                )
                self.assertFalse(ok_diff_mem)
            finally:
                other_con.close()

            # Modificarea hashului fișierului sursă invalidează reutilizarea
            raw_file.write_bytes(raw_file.read_bytes() + b"tamper")
            ok_diff_hash, _ = check_sample_reuse(
                out_file,
                p=0.5,
                seed=42,
                con=self.con,
                dataset_id="jan",
                period=period,
                source_files=[raw_file],
            )
            self.assertFalse(ok_diff_hash)

    def test_overwrite_replaces_incompatible_or_corrupt_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "corrupt_sample.parquet"
            manifest_file = get_manifest_path(out_file)

            # Scriem artefacte corupte / incompatibile existente
            out_file.write_text("corrupt content", encoding="utf-8")
            manifest_file.write_text("{}", encoding="utf-8")

            # Fără overwrite=True, refuză
            with self.assertRaises(ValueError):
                build_sample(self.con, 0.5, 42, out_file, overwrite=False)

            # Cu overwrite=True, înlocuiește fișierele și reconstruiește cu succes
            result = build_sample(self.con, 0.5, 42, out_file, overwrite=True)
            self.assertFalse(result.reused)
            self.assertTrue(out_file.exists())
            self.assertTrue(manifest_file.exists())
            self.assertGreater(out_file.stat().st_size, 0)
            self.assertGreaterEqual(result.row_count, 0)


    def test_overwrite_failure_preserves_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "sample.parquet"

            # Construim initial un esantion valid.
            build_sample(self.con, 0.5, 42, out_file)
            manifest_file = get_manifest_path(out_file)

            # Salvam continutul original al ambelor fisiere.
            original_parquet = out_file.read_bytes()
            original_manifest = manifest_file.read_bytes()

            # Simulam o eroare SQL la regenerare.
            with mock.patch.object(
                artifacts,
                "get_export_sample_sql",
                return_value="SELECT * FROM missing_table_forced_error",
            ):
                with self.assertRaises(duckdb.Error):
                    build_sample(
                        self.con,
                        0.5,
                        42,
                        out_file,
                        overwrite=True,
                    )

            # Fisierele vechi trebuie sa existe in continuare.
            self.assertTrue(out_file.exists())
            self.assertTrue(manifest_file.exists())

            # Continutul lor trebuie sa fie neschimbat.
            self.assertEqual(out_file.read_bytes(), original_parquet)
            self.assertEqual(manifest_file.read_bytes(), original_manifest)

if __name__ == "__main__":
    unittest.main()
