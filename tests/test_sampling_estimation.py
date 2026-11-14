import unittest

import pandas as pd

from src.sampling import estimate_counts, format_sample_results


class SamplingEstimationTests(unittest.TestCase):
    def test_invalid_probabilities_rejected(self) -> None:
        for bad_p in (0, -0.1, 1.01, float("nan"), float("inf"), float("-inf"), True, False, "0.1"):
            with self.subTest(p=bad_p), self.assertRaises(ValueError):
                estimate_counts([("00", 2)], bad_p)

    def test_pairs_dict_and_dataframe_preserve_keys_and_scale_once(self) -> None:
        self.assertEqual(
            estimate_counts([("00", 2), ("01", 3)], 0.1),
            [("00", 20.0), ("01", 30.0)],
        )
        self.assertEqual(
            estimate_counts({"00": 2, "01": 3}, 0.25),
            {"00": 8.0, "01": 12.0},
        )
        df = pd.DataFrame({"group_key": ["0", "1"], "value": [2, 4]})
        est_df = estimate_counts(df, 0.5)
        self.assertEqual(list(est_df["group_key"]), ["0", "1"])
        self.assertEqual(list(est_df["value"]), [4.0, 8.0])
        # DataFrame-ul original rămâne nemodificat
        self.assertEqual(list(df["value"]), [2, 4])

    def test_uniform_validation_across_representations(self) -> None:
        for bad_df in (
            pd.DataFrame({"group_key": ["00"], "value": [True]}),
            pd.DataFrame({"group_key": ["00"], "value": ["2"]}),
            pd.DataFrame({"group_key": ["00"], "value": [float("nan")]}),
            pd.DataFrame({"group_key": ["00"], "value": [-1.0]}),
        ):
            with self.subTest(df=bad_df), self.assertRaises(ValueError):
                estimate_counts(bad_df, 0.1)

        for bad_seq in ([("00", True)], [("00", "2")], [("00", float("inf"))], [("00", -2)]):
            with self.subTest(seq=bad_seq), self.assertRaises(ValueError):
                estimate_counts(bad_seq, 0.1)

    def test_overflow_to_infinite_rejected(self) -> None:
        with self.assertRaises(ValueError):
            estimate_counts([1], 5e-324)

    def test_format_sample_results_metadata_and_empty_status(self) -> None:
        ok_rows = format_sample_results(
            [("0", 10.0), ("1", 20.0)],
            run_id="run-1",
            dataset_id="jan",
            question="distance",
            sample_rate=0.1,
            seed=42,
        )
        self.assertEqual(len(ok_rows), 2)
        self.assertTrue(all(row["status"] == "ok" and row["method"] == "sample" for row in ok_rows))

        empty_rows = format_sample_results(
            [("0", 0.0), ("1", 0.0)],
            run_id="run-1",
            dataset_id="jan",
            question="distance",
            sample_rate=0.1,
            seed=42,
        )
        self.assertTrue(all(row["status"] == "empty_sample" for row in empty_rows))


if __name__ == "__main__":
    unittest.main()
