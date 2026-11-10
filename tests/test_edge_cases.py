import unittest

import pandas as pd

from src.metrics import (
    calculate_distance_total_variation,
    calculate_hours_error,
    evaluate,
)


def frame(keys, values):
    return pd.DataFrame({"group_key": keys, "value": values})


class MetricEdgeCaseTests(unittest.TestCase):
    def test_manual_hourly_error_is_one_third(self):
        exact = frame(["00", "01", "08", "12", "18", "23"], [2, 3, 3, 2, 1, 1])
        estimate = frame(["00", "01", "08", "12", "18", "23"], [3, 3, 3, 3, 0, 0])
        self.assertAlmostEqual(calculate_hours_error(exact, estimate), 1 / 3)

    def test_manual_tvd_is_one_quarter(self):
        exact = frame(["0", "1", "2", "3", "4"], [1, 2, 3, 3, 3])
        estimated = frame(["0", "1", "2", "3", "4"], [3, 3, 3, 3, 0])
        self.assertAlmostEqual(calculate_distance_total_variation(exact, estimated), 0.25)

    def test_missing_categories_are_zero_filled_by_outer_merge(self):
        exact = frame(["a", "b"], [1, 1])
        estimate = frame(["a"], [1])
        self.assertAlmostEqual(calculate_hours_error(exact, estimate), 0.5)

    def test_tvd_zero_total_statuses(self):
        exact = frame(["a"], [2])
        empty = frame(["a"], [0])
        result = calculate_distance_total_variation(exact, empty, with_status=True)
        self.assertEqual((result.status, result.value), ("empty_sample", None))
        result = calculate_distance_total_variation(empty, empty, with_status=True)
        self.assertEqual((result.status, result.value), ("not_applicable", None))

    def test_hour_zero_total_statuses(self):
        exact = frame(["a"], [2])
        empty = frame(["a"], [0])
        result = calculate_hours_error(exact, empty, with_status=True)
        self.assertEqual((result.status, result.value), ("empty_sample", 1.0))
        result = calculate_hours_error(empty, empty, with_status=True)
        self.assertEqual((result.status, result.value), ("not_applicable", None))

    def test_nan_negative_duplicate_and_missing_column_inputs_rejected(self):
        cases = (
            frame(["a"], [float("nan")]),
            frame(["a"], [float("inf")]),
            frame(["a"], [-1]),
            frame(["a"], ["1"]),
            frame(["a", "a"], [1, 2]),
            pd.DataFrame({"group_key": ["a"]}),
        )
        valid = frame(["a"], [1])
        for invalid in cases:
            with self.subTest(invalid=invalid.to_dict()), self.assertRaises((ValueError, TypeError)):
                calculate_hours_error(invalid, valid)

    def test_null_keys_and_incompatible_key_formats_rejected(self):
        valid = frame(["a"], [1])
        for invalid in (frame([None], [1]), frame([1], [1])):
            with self.subTest(invalid=invalid.to_dict()), self.assertRaises(ValueError):
                calculate_hours_error(valid, invalid)

    def test_evaluate_preserves_metric_status_for_export(self):
        rows = [("a", 2)]
        self.assertEqual(evaluate(rows, [("a", 0)], "distance"),
                         {"status": "empty_sample", "value": None})

    def test_category_order_invariance(self):
        exact = frame(["a", "b", "c"], [2, 3, 5])
        estimated = frame(["c", "a", "b"], [5, 2, 3])
        self.assertEqual(calculate_hours_error(exact, estimated), 0.0)
        self.assertEqual(calculate_distance_total_variation(exact, estimated), 0.0)


if __name__ == "__main__":
    unittest.main()
