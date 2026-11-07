import unittest

import pandas as pd

from src.plots import DISTANCE_ORDER, plot_distance_distribution


def frame(values):
    return pd.DataFrame({"group_key": ["0", "1", "2", "3", "4"], "value": values})


class PlotTests(unittest.TestCase):
    def test_normalized_data_labels_order_and_metadata(self):
        fig = plot_distance_distribution(
            frame([1, 2, 3, 3, 3]), frame([1, 1, 1, 1, 0]),
            sample_rate=1 / 3, analysis_period="Jan 2025", random_seed=42,
        )
        self.assertEqual(list(fig.data[0].x), DISTANCE_ORDER)
        for actual, expected in zip(fig.data[0].y, [100 / 12, 200 / 12, 25, 25, 25]):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(fig.data[1].y, [25, 25, 25, 25, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(fig.layout.yaxis.range, (0, 100))
        self.assertEqual(fig.layout.yaxis.ticksuffix, "%")
        self.assertEqual(fig.layout.meta, {"analysis_period": "Jan 2025", "random_seed": 42})
        self.assertEqual(fig.layout.updatemenus[0].buttons[0].label, "33.3333%")
        self.assertIn("miles", DISTANCE_ORDER[-1])

    def test_sample_percentage_selector_keeps_axis_scale(self):
        fig = plot_distance_distribution(
            frame([1, 1, 1, 1, 1]), frame([1, 1, 1, 1, 1]), sample_rate=0.1,
            sample_options={0.1: frame([1, 1, 1, 1, 1]), 0.2: frame([1, 2, 3, 4, 5])},
        )
        self.assertEqual(len(fig.layout.updatemenus[0].buttons), 2)
        self.assertEqual(fig.layout.yaxis.range, (0, 100))
        self.assertEqual([trace.visible for trace in fig.data], [True, True, False])

    def test_empty_sample_is_labeled_without_crashing(self):
        fig = plot_distance_distribution(
            frame([1, 2, 3, 3, 3]), frame([0, 0, 0, 0, 0]),
            sample_rate=0.1, status="empty_sample",
        )
        self.assertTrue(any("Empty sample" in annotation.text for annotation in fig.layout.annotations))
        self.assertEqual(list(fig.data[1].y), [0, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
