import unittest

from src.figures_hours import build_hours_figure


class HoursFigureTests(unittest.TestCase):
    def setUp(self):
        identity = dict(run_id="pilot_test", dataset_id="jan", config_version="1")
        self.manifest = {
            **identity, "status": "complete", "stage": "pilot", "data_kind": "real",
            "period": {"start": "2025-01-01T00:00:00", "end": "2025-02-01T00:00:00"},
            "protocol": {"sample_rates": [0.01, 0.10], "seeds": [42]},
        }
        self.rows = [
            dict(**identity, question="hours", method=method, sample_rate=rate,
                 seed=seed, group_key=f"{hour:02d}", value=str(hour * factor), status="ok")
            for method, rate, seed, factor in (
                ("exact", "1.0", "", 100), ("sample", "0.01", "42", 120),
                ("sample", "0.1", "42", 110),
            )
            for hour in reversed(range(24))
        ]

    def test_ordered_hours_and_selector_keep_exact_visible(self):
        fig = build_hours_figure(self.rows, self.manifest)
        self.assertEqual(list(fig.data[0].x), [f"{hour:02d}" for hour in range(24)])
        expected = [hour * 100 / 276 for hour in range(24)]
        for actual, wanted in zip(fig.data[0].y, expected):
            self.assertAlmostEqual(actual, wanted)
        self.assertAlmostEqual(sum(fig.data[0].y), 100.0)
        self.assertAlmostEqual(sum(fig.data[1].y), 100.0)
        self.assertEqual(fig.layout.yaxis.range, (0, 100))
        self.assertEqual(fig.layout.yaxis.ticksuffix, "%")
        self.assertEqual([trace.visible for trace in fig.data], [True, True, False])
        buttons = fig.layout.updatemenus[0].buttons
        self.assertEqual([button.label for button in buttons], ["1%", "10%"])
        self.assertEqual(buttons[0].args[0]["visible"], [True, True, False])
        self.assertEqual(buttons[1].args[0]["visible"], [True, False, True])
        self.assertGreater(fig.layout.yaxis.range[1], max(fig.data[1].y))
        self.assertIn("[2025-01-01, 2025-02-01)", fig.layout.title.text)
        self.assertIn("Seed 42", fig.layout.title.text)

    def test_metric_error_is_displayed_and_updates_with_selector(self):
        fig = build_hours_figure(
            self.rows, self.manifest,
            metric_values={0.01: 0.021589327931150537, 0.1: 0.006174668935567683},
        )
        self.assertIn("Eroare pe ore față de exact: 2.1589%", fig.layout.title.text)
        self.assertIn("Eroare pe ore față de exact: 0.6175%",
                      fig.layout.updatemenus[0].buttons[1].args[1]["title.text"])

    def test_empty_sample_is_labeled_in_initial_view_and_selector(self):
        for row in self.rows:
            if row["sample_rate"] == "0.01":
                row.update(value="0", status="empty_sample")
        fig = build_hours_figure(self.rows, self.manifest)
        self.assertIn("eșantion gol", fig.layout.title.text)
        self.assertNotIn("eșantion gol", fig.layout.updatemenus[0].buttons[1].args[1]["title.text"])

    def test_missing_hour_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "toate cele 24 de ore"):
            build_hours_figure(self.rows[1:], self.manifest)


if __name__ == "__main__":
    unittest.main()
