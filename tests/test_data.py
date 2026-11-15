import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from src.config import PROJECT_ROOT
from src.data import (
    format_zone_name,
    load_zone_lookup,
    register_trips,
)
from src.queries import query_counts

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"
TRIPS_FIXTURE = FIXTURE_DIR / "trips.csv"
ZONES_FIXTURE = FIXTURE_DIR / "zones.csv"


class TestDataModule(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.start = datetime(2025, 1, 1)
        self.end = datetime(2025, 2, 1)

    def tearDown(self):
        self.con.close()

    def test_register_trips_fixture_filtering(self):
        """Verifică că din cele 20 de rânduri brute din fixture rămân exact 12 eligibile."""
        register_trips(self.con, TRIPS_FIXTURE, self.start, self.end)
        count = self.con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        self.assertEqual(count, 12, f"Așteptat 12 rânduri eligibile pe fixture, obținut {count}")

    def test_query_integration(self):
        """Verifică integrarea cu interogările de ore și distanțe ale lui Octavian."""
        register_trips(self.con, TRIPS_FIXTURE, self.start, self.end)
        
        # Test ore (01)
        hours_df = query_counts(self.con, "hours", "trips").df()
        self.assertEqual(len(hours_df), 24)
        total_hours_val = hours_df["value"].sum()
        self.assertEqual(total_hours_val, 12)

        # Test distanțe (02)
        dist_df = query_counts(self.con, "distance", "trips").df()
        self.assertEqual(len(dist_df), 5)
        self.assertEqual(dist_df["value"].sum(), 12)

    def test_zone_formatting_and_duplicate_handling(self):
        """Verifică etichetarea zonelor și detecția ID-urilor duplicate."""
        lookup = load_zone_lookup(ZONES_FIXTURE)
        
        # ID 0 devine Zonă lipsă
        self.assertEqual(format_zone_name(0, lookup), "Zonă lipsă")
        # ID absent (99) devine Zonă necunoscută (99)
        self.assertEqual(format_zone_name(99, lookup), "Zonă necunoscută (99)")

        # Verificare eroare la LocationID duplicat
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
            tmp.write("LocationID,Borough,Zone\n1,Manhattan,ZoneA\n1,Manhattan,ZoneB\n")
            tmp_path = Path(tmp.name)

        try:
            with self.assertRaises(ValueError):
                load_zone_lookup(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()