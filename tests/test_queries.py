import unittest
from pathlib import Path

import duckdb

from src.metrics import calculate_distance_total_variation, calculate_hours_error
from src.queries import query_counts
from src.sampling import estimate_counts


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.conn = duckdb.connect()
        fixture = (Path(__file__).parent / "fixtures" / "trips.csv").as_posix()
        self.conn.execute(f"""
            CREATE TABLE trips AS
            SELECT tpep_pickup_datetime AS pickup_at,
                   trip_distance AS distance_miles,
                   PULocationID AS pickup_zone, fixture_id
            FROM read_csv_auto('{fixture}')
            WHERE fixture_id BETWEEN 1 AND 12 OR fixture_id BETWEEN 16 AND 20
        """)
        self.conn.execute("CREATE TABLE sample_trips AS SELECT * FROM trips WHERE fixture_id IN (1, 3, 6, 9)")

    def tearDown(self):
        self.conn.close()

    def test_query_counts_hours_for_both_sources(self):
        for source, expected in (("trips", 12), ("sample_trips", 4)):
            with self.subTest(source=source):
                rows = query_counts(self.conn, "hours", source).df()
                self.assertEqual(len(rows), 24)
                self.assertEqual(int(rows.value.sum()), expected)
                self.assertTrue(all(isinstance(v, int) for v in rows.value))

    def test_query_counts_distance_for_both_sources(self):
        exact = query_counts(self.conn, "distance", "trips").df()
        sampled = query_counts(self.conn, "distance", "sample_trips").df()
        self.assertEqual(list(exact.group_key), ["0", "1", "2", "3", "4"])
        self.assertEqual(list(exact.value), [1, 2, 3, 3, 3])
        self.assertEqual(int(sampled.value.sum()), 4)

    def test_identical_exact_results_have_zero_metric_error(self):
        hours = query_counts(self.conn, "hours", "trips").df()
        distance = query_counts(self.conn, "distance", "trips").df()
        self.assertEqual(calculate_hours_error(hours, hours), 0.0)
        self.assertEqual(calculate_distance_total_variation(distance, distance), 0.0)

    def test_invalid_source_fails_before_sql(self):
        self.conn.close()
        with self.assertRaises(ValueError):
            query_counts(self.conn, "hours", "malicious_table")

    def test_empty_views_return_all_categories(self):
        self.conn.execute("CREATE TABLE empty_trips AS SELECT * FROM trips WHERE false")
        hours = query_counts(self.conn, "hours", "trips").df()
        # Explicitly query an allowed source that points at an empty view.
        self.conn.execute("DROP TABLE sample_trips")
        self.conn.execute("CREATE VIEW sample_trips AS SELECT * FROM empty_trips")
        hours = query_counts(self.conn, "hours", "sample_trips").df()
        distance = query_counts(self.conn, "distance", "sample_trips").df()
        self.assertEqual(len(hours), 24)
        self.assertEqual(int(hours.value.sum()), 0)
        self.assertEqual(list(distance.value), [0, 0, 0, 0, 0])

    def test_weighting_occurs_once_after_raw_sql_counts(self):
        raw = query_counts(self.conn, "distance", "sample_trips").df()
        self.assertEqual(list(raw.value), [1, 1, 1, 1, 0])
        estimated = estimate_counts(raw, 1 / 3)
        self.assertEqual(list(estimated.value), [3, 3, 3, 3, 0])
        self.assertEqual(float(estimated.value.sum()), 12)

    def test_probability_validation(self):
        for p in (0, -0.1, 1.01, float("nan"), float("inf"), True, "0.1"):
            with self.subTest(p=p), self.assertRaises(ValueError):
                estimate_counts([1], p)

    def test_distance_boundaries_are_explicit(self):
        self.conn.execute("""
            CREATE TABLE boundary_trips AS
            SELECT TIMESTAMP '2025-01-01 00:00:00' AS pickup_at,
                   d::DOUBLE AS distance_miles, 1 AS pickup_zone
            FROM (VALUES (0.5), (1), (2), (5), (10)) t(d)
        """)
        self.conn.execute("DROP TABLE sample_trips")
        self.conn.execute("CREATE TABLE sample_trips AS SELECT * FROM boundary_trips")
        result = query_counts(self.conn, "distance", "sample_trips").df()
        self.assertEqual(list(result.value), [1, 1, 1, 1, 1])

    def test_hourly_and_distance_queries_share_eligible_population(self):
        hours = query_counts(self.conn, "hours", "trips").df()
        distance = query_counts(self.conn, "distance", "trips").df()
        self.assertEqual(int(hours.value.sum()), 12)
        self.assertEqual(int(distance.value.sum()), 12)


if __name__ == "__main__":
    unittest.main()
