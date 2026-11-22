import unittest
from unittest.mock import patch

from src.demo import main


class DemoTests(unittest.TestCase):
    def test_path_traversal_run_id_is_rejected_before_disk_access(self):
        with patch("src.demo.render_pilot") as render_pilot:
            with self.assertRaisesRegex(ValueError, "run_id invalid"):
                main("../outside")
        render_pilot.assert_not_called()
