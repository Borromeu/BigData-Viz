import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import duckdb

from src.config import PROJECT_ROOT
from src.data import (
    format_zone_name,
    load_zone_lookup,
    register_trips,
    validate_schema,
)
from src.queries import query_counts

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"
TRIPS_FIXTURE = FIXTURE_DIR / "trips.csv"
ZONES_FIXTURE = FIXTURE_DIR / "zones.csv"


class TestDataModuleExtensive(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.start = datetime(2025, 1, 1)
        self.end = datetime(2025, 2, 1)

    def tearDown(self):
        self.con.close()

    def test_fixture_eligible_and_exclusions_reconciliation(self):
        """Verifică că din 20 rânduri brute rămân 12 eligibile."""
        register_trips(self.con, TRIPS_FIXTURE, self.start, self.end)
        count = self.con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        self.assertEqual(count, 12)

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