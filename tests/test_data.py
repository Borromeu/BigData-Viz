import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import duckdb

from src.config import PROJECT_ROOT
from src.data import (
    _QUALITY_EXCLUSIONS_SQL,
    _get_source_sql,
    format_zone_name,
    load_zone_lookup,
    register_trips,
    validate_schema,
    verify_data_manifest,
)
from src.queries import query_counts

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"
TRIPS_FIXTURE = FIXTURE_DIR / "trips.csv"
ZONES_FIXTURE = FIXTURE_DIR / "zones.csv"


class TestManifestVerification(unittest.TestCase):
    """Teste automate pentru verificarea integrității manifestului (Cerința A)."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_manifest_"))
        self.sample_file = self.temp_dir / "sample.parquet"
        self.sample_content = b"test content for sha256 manifest check"
        self.sample_file.write_bytes(self.sample_content)

        self.correct_hash = hashlib.sha256(self.sample_content).hexdigest()
        self.correct_size = len(self.sample_content)

        self.manifest_path = self.temp_dir / "data_manifest.json"
        self.manifest_data = {
            "generated_at": datetime.now().isoformat(),
            "files": [
                {
                    "filename": "sample.parquet",
                    "relative_path": "data/raw/sample.parquet",
                    "url": "http://example.com/sample.parquet",
                    "size_bytes": self.correct_size,
                    "sha256": self.correct_hash,
                }
            ],
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest_data, f)

    def tearDown(self):
        for item in self.temp_dir.glob("*"):
            item.unlink()
        self.temp_dir.rmdir()

    def test_verify_manifest_success(self):
        """Un fișier valid cu dimensiune și hash corecte trece verificarea."""
        res = verify_data_manifest(self.manifest_path, [self.sample_file])
        self.assertTrue(res)

    def test_verify_manifest_modified_content_same_size(self):
        """Un fișier modificat cu aceeași dimensiune dar hash diferit produce eroare SHA-256."""
        modified_content = b"TEST CONTENT FOR SHA256 MANIFEST CHECK"  # Aceeași lungime, octeți diferiți
        self.sample_file.write_bytes(modified_content)

        with self.assertRaises(ValueError) as ctx:
            verify_data_manifest(self.manifest_path, [self.sample_file])
        self.assertIn("Amprentă SHA-256 necorespunzătoare", str(ctx.exception))

    def test_verify_manifest_missing_file_on_disk(self):
        """Un fișier lipsă de pe disc produce FileNotFoundError."""
        missing_file = self.temp_dir / "non_existent.parquet"
        self.manifest_data["files"].append({
            "filename": "non_existent.parquet",
            "relative_path": "data/raw/non_existent.parquet",
            "url": "http://example.com/non_existent.parquet",
            "size_bytes": 100,
            "sha256": "dummyhash",
        })
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest_data, f)

        with self.assertRaises(FileNotFoundError) as ctx:
            verify_data_manifest(self.manifest_path, [missing_file])
        self.assertIn("nu există pe disc", str(ctx.exception))

    def test_verify_manifest_unregistered_file(self):
        """Un fișier care nu există în manifest produce ValueError."""
        unregistered_file = self.temp_dir / "unregistered.parquet"
        unregistered_file.write_bytes(b"data")

        with self.assertRaises(ValueError) as ctx:
            verify_data_manifest(self.manifest_path, [unregistered_file])
        self.assertIn("nu este înregistrat în manifest", str(ctx.exception))

    def test_verify_manifest_does_not_modify_manifest_file(self):
        """Verificarea manifestului nu modifică conținutul fișierului JSON de pe disc."""
        content_before = self.manifest_path.read_text(encoding="utf-8")
        verify_data_manifest(self.manifest_path, [self.sample_file])
        content_after = self.manifest_path.read_text(encoding="utf-8")
        self.assertEqual(content_before, content_after)


class TestExclusionsReconciliation(unittest.TestCase):
    """Teste automate pentru reconcilierea aritmetică și excluderile disjuncte (Cerința B)."""

    def setUp(self):
        self.con = duckdb.connect()
        self.start = datetime(2025, 1, 1)
        self.end = datetime(2025, 2, 1)

    def tearDown(self):
        self.con.close()

    def test_fixture_exclusions_exact_reconciliation(self):
        """Verifică reconcilierea exactă 20 = 12 + 1 + 2 + 3 + 2 pe fixture de test."""
        register_trips(self.con, TRIPS_FIXTURE, self.start, self.end)
        eligible_count = self.con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]

        source_sql = _get_source_sql([TRIPS_FIXTURE])
        query = _QUALITY_EXCLUSIONS_SQL.format(
            source_sql=source_sql,
            start_str=self.start.strftime("%Y-%m-%d %H:%M:%S"),
            end_str=self.end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        res = self.con.execute(query).fetchone()

        raw_rows, missing_ts, out_of_period, invalid_dist, nonpositive_dist = res
        excluded_total = missing_ts + out_of_period + invalid_dist + nonpositive_dist

        self.assertEqual(raw_rows, 20)
        self.assertEqual(eligible_count, 12)
        self.assertEqual(missing_ts, 1)
        self.assertEqual(out_of_period, 2)
        self.assertEqual(invalid_dist, 3)
        self.assertEqual(nonpositive_dist, 2)

        # Reconciliere aritmetică 20 = 12 + 8
        self.assertEqual(raw_rows, eligible_count + excluded_total)

    def test_overlapping_issues_counted_once(self):
        """Verifică izolarea disjunctă: un rând cu timestamp lipsă ȘI distanță negativă este numărat o singură dată."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
            tmp.write(
                "tpep_pickup_datetime,trip_distance,PULocationID\n"
                ",-5.0,1\n"  # Rând cu 2 probleme simultane (timestamp lipsă + distanță negativă)
                "2025-01-15 10:00:00,2.5,1\n"  # Rând eligibil
            )
            tmp_path = Path(tmp.name)

        try:
            source_sql = _get_source_sql([tmp_path])
            query = _QUALITY_EXCLUSIONS_SQL.format(
                source_sql=source_sql,
                start_str=self.start.strftime("%Y-%m-%d %H:%M:%S"),
                end_str=self.end.strftime("%Y-%m-%d %H:%M:%S"),
            )
            res = self.con.execute(query).fetchone()

            raw_rows, missing_ts, out_of_period, invalid_dist, nonpositive_dist = res
            excluded_total = missing_ts + out_of_period + invalid_dist + nonpositive_dist

            self.assertEqual(raw_rows, 2)
            self.assertEqual(missing_ts, 1)
            self.assertEqual(out_of_period, 0)
            self.assertEqual(invalid_dist, 0)
            self.assertEqual(nonpositive_dist, 0)  # NU este dublu numărat aici
            self.assertEqual(excluded_total, 1)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


class TestDataModuleIntegration(unittest.TestCase):
    """Teste de integrare cu modulele existente."""

    def setUp(self):
        self.con = duckdb.connect()
        self.start = datetime(2025, 1, 1)
        self.end = datetime(2025, 2, 1)

    def tearDown(self):
        self.con.close()

    def test_query_integration(self):
        """Verifică integrarea cu interogările de ore și distanțe ale lui Octavian."""
        register_trips(self.con, TRIPS_FIXTURE, self.start, self.end)

        hours_df = query_counts(self.con, "hours", "trips").df()
        self.assertEqual(len(hours_df), 24)
        self.assertEqual(hours_df["value"].sum(), 12)

        dist_df = query_counts(self.con, "distance", "trips").df()
        self.assertEqual(len(dist_df), 5)
        self.assertEqual(dist_df["value"].sum(), 12)

    def test_zone_formatting_and_duplicate_handling(self):
        """Verifică etichetarea zonelor și eroare la LocationID duplicat."""
        lookup = load_zone_lookup(ZONES_FIXTURE)
        self.assertEqual(format_zone_name(0, lookup), "Zonă lipsă")
        self.assertEqual(format_zone_name(99, lookup), "Zonă necunoscută (99)")

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
            tmp.write("LocationID,Borough,Zone\n1,Manhattan,ZoneA\n1,Manhattan,ZoneB\n")
            tmp_path = Path(tmp.name)

        try:
            with self.assertRaises(ValueError):
                load_zone_lookup(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_missing_column_schema_validation(self):
        """Verifică că o coloană obligatorie lipsă produce o eroare explicită."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
            tmp.write("tpep_pickup_datetime,trip_distance\n2025-01-15 00:00:00,1.5\n")
            tmp_path = Path(tmp.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                validate_schema(self.con, [tmp_path])
            self.assertIn("PULocationID", str(ctx.exception))
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_path_with_apostrophe_and_spaces(self):
        """Verifică citirea fără erori a căilor cu apostrof și spații."""
        temp_dir = Path(tempfile.mkdtemp(prefix="Stefan's test "))
        test_file = temp_dir / "trips.csv"
        with open(TRIPS_FIXTURE, "r") as f_in, open(test_file, "w") as f_out:
            f_out.write(f_in.read())

        try:
            register_trips(self.con, test_file, self.start, self.end)
            count = self.con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
            self.assertEqual(count, 12)
        finally:
            if test_file.exists():
                test_file.unlink()
            if temp_dir.exists():
                temp_dir.rmdir()


if __name__ == "__main__":
    unittest.main()