from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_wrapper.watchpoints import WatchpointManager


class WatchpointManagerTests(unittest.TestCase):
    def test_enable_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = WatchpointManager()
            config = manager.enable(0, "score.csv", base_dir=Path(tmp))
            self.assertEqual(config.watchpoint, 0)
            self.assertTrue(config.path.is_absolute())
            self.assertTrue(config.path.exists())
            self.assertIs(manager.get(0), config)
            manager.close()

    def test_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = WatchpointManager()
            manager.enable(0, "score.csv", base_dir=Path(tmp))
            self.assertTrue(manager.disable(0))
            self.assertFalse(manager.disable(0))
            self.assertIsNone(manager.get(0))
            manager.close()

    def test_multiple_configs_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = WatchpointManager()
            manager.enable(2, "two.csv", base_dir=Path(tmp))
            manager.enable(1, "one.csv", base_dir=Path(tmp))
            self.assertEqual([c.watchpoint for c in manager.configs()], [1, 2])
            manager.close()

    def test_reenable_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = WatchpointManager()
            first = manager.enable(0, "a.csv", base_dir=Path(tmp))
            second = manager.enable(0, "b.csv", base_dir=Path(tmp))
            self.assertIsNot(first, second)
            self.assertEqual(len(manager.configs()), 1)
            self.assertEqual(manager.get(0).path, second.path)
            manager.close()


if __name__ == "__main__":
    unittest.main()
