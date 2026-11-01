import importlib
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src import config


class ConfigTests(unittest.TestCase):
    def test_dataset_periods_and_files(self):
        jan = config.get_dataset("jan")
        q1 = config.get_dataset("q1")

        self.assertEqual(jan.start, datetime(2025, 1, 1))
        self.assertEqual(jan.end, datetime(2025, 2, 1))
        self.assertEqual(q1.end, datetime(2025, 4, 1))

        self.assertEqual(
            [path.name for path in jan.files],
            ["yellow_tripdata_2025-01.parquet"],
        )
        self.assertEqual(
            [path.name for path in q1.files],
            [
                "yellow_tripdata_2025-01.parquet",
                "yellow_tripdata_2025-02.parquet",
                "yellow_tripdata_2025-03.parquet",
            ],
        )

    def test_unknown_names_are_rejected(self):
        with self.assertRaises(ValueError):
            config.get_dataset("unknown")

        with self.assertRaises(ValueError):
            config.get_stage("unknown")

    def test_invalid_sample_rates_are_rejected(self):
        invalid = (
            0, -0.1, 1.1,
            float("nan"), float("inf"),
            True, "0.1",
        )

        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    config.validate_sample_rate(value)

        # Folosit inclusiv pentru testul de identitate exact–sample.
        config.validate_sample_rate(1)

    def test_invalid_seeds_are_rejected(self):
        for value in (True, 42.5, "42", -1, 4_294_967_296):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    config.validate_seed(value)

        config.validate_seed(42)

    def test_empty_files_and_invalid_period_are_rejected(self):
        start = datetime(2025, 1, 1)
        end = datetime(2025, 2, 1)
        files = (Path("example.parquet"),)

        with self.assertRaises(ValueError):
            config.DatasetConfig("test", (), start, end)

        with self.assertRaises(ValueError):
            config.DatasetConfig("test", files, end, start)

        with self.assertRaises(ValueError):
            config.DatasetConfig("test", files, start, start)

    def test_stage_settings_and_case_counts(self):
        pilot = config.get_stage("pilot")
        final = config.get_stage("final")

        self.assertEqual(pilot.sample_rates, (0.01, 0.10))
        self.assertEqual(pilot.seeds, (42,))
        self.assertEqual(pilot.repeats, 3)

        self.assertEqual(final.sample_rates, (0.01, 0.05, 0.10))
        self.assertEqual(final.seeds, (42, 43, 44))
        self.assertEqual(final.repeats, 5)

        pilot_cases = len(pilot.questions) * (
            1 + len(pilot.sample_rates) * len(pilot.seeds)
        )
        final_cases = 2 * len(final.questions) * (
            1 + len(final.sample_rates) * len(final.seeds)
        )

        self.assertEqual(pilot_cases, 6)
        self.assertEqual(pilot_cases * pilot.repeats, 18)
        self.assertEqual(final_cases, 60)
        self.assertEqual(final_cases * final.repeats, 300)

    def test_paths_do_not_depend_on_working_directory(self):
        expected_root = Path(__file__).resolve().parents[1]
        original_directory = Path.cwd()

        try:
            with tempfile.TemporaryDirectory() as directory:
                os.chdir(directory)
                importlib.reload(config)

                self.assertEqual(config.PROJECT_ROOT, expected_root)
                self.assertTrue(config.RAW_DIR.is_absolute())
                self.assertEqual(
                    config.get_dataset("jan").files[0].parent,
                    expected_root / "data" / "raw",
                )
        finally:
            os.chdir(original_directory)
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()