from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_wrapper.parser import WatchpointHit
from fs_uae_debug_wrapper.watchpoints import WatchpointManager, next_log_path


def make_hit(value: int, watchpoint: int = 0) -> WatchpointHit:
    return WatchpointHit(
        watchpoint=watchpoint,
        address=0x574,
        size="W",
        access="W",
        value=value,
        pc=0xC28C,
        trailer="CPUDW (000)",
        raw="Memwatch: break",
    )


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


class ChangeFilterTests(unittest.TestCase):
    def test_define_watch_resets_last_value(self) -> None:
        manager = WatchpointManager()
        watch = manager.define_watch(1, "ball.x", 0x574, 2)
        self.assertEqual(watch.name, "ball.x")
        self.assertIsNone(watch.last_value)
        self.assertEqual([w.watchpoint for w in manager.watches()], [1])

    def test_first_hit_is_not_duplicate(self) -> None:
        manager = WatchpointManager()
        manager.define_watch(1, "ball.x", 0x574, 2)
        self.assertFalse(manager.is_duplicate(make_hit(0x5B, watchpoint=1)))
        manager.observe(make_hit(0x5B, watchpoint=1))
        self.assertTrue(manager.is_duplicate(make_hit(0x5B, watchpoint=1)))
        self.assertFalse(manager.is_duplicate(make_hit(0x5C, watchpoint=1)))

    def test_unwatched_hit_is_never_duplicate(self) -> None:
        manager = WatchpointManager()
        self.assertFalse(manager.is_duplicate(make_hit(0x5B, watchpoint=9)))

    def test_plain_watchpoint_is_not_filtered(self) -> None:
        manager = WatchpointManager()
        manager.observe(make_hit(0x5B, watchpoint=3))
        self.assertFalse(manager.is_duplicate(make_hit(0x5B, watchpoint=3)))


class LogPathTests(unittest.TestCase):
    def test_first_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = next_log_path(Path(tmp), ["ball.x"])
            self.assertEqual(path.name, "ball.x_000.csv")

    def test_counter_increments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "ball.x_ball.y_000.csv").touch()
            (base / "ball.x_ball.y_001.csv").touch()
            path = next_log_path(base, ["ball.x", "ball.y"])
            self.assertEqual(path.name, "ball.x_ball.y_002.csv")

    def test_gap_is_filled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a_000.csv").touch()
            (base / "a_002.csv").touch()
            self.assertEqual(next_log_path(base, ["a"]).name, "a_001.csv")


if __name__ == "__main__":
    unittest.main()
