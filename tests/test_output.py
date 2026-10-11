from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fs_uae_debug_shell.eventlog import EventLogError
from fs_uae_debug_shell.output import OutputMode, OutputRouter, default_logfile_name
from fs_uae_debug_shell.parser import WatchpointHit

FIXED_NOW = datetime(2026, 10, 11, 19, 30, 45, 123000)


def make_hit(value: int = 0x5B, watchpoint: int = 0) -> WatchpointHit:
    return WatchpointHit(
        watchpoint=watchpoint,
        address=0x574,
        size="W",
        access="W",
        value=value,
        pc=0xC28C,
        trailer="CPUDW (000)",
        raw="Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)",
    )


def make_router(case: unittest.TestCase, tmp: str) -> OutputRouter:
    router = OutputRouter(Path(tmp), now=lambda: FIXED_NOW)
    case.addCleanup(router.close)
    return router


class ModeTests(unittest.TestCase):
    def test_default_is_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            self.assertIs(router.mode, OutputMode.SHELL)
            self.assertTrue(router.display_enabled)
            self.assertFalse(router.log_enabled)
            self.assertFalse(router.show_counters)

    def test_log_mode_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_mode(OutputMode.LOG)
            self.assertFalse(router.display_enabled)
            self.assertTrue(router.log_enabled)
            self.assertTrue(router.show_counters)

    def test_both_mode_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_mode(OutputMode.BOTH)
            self.assertTrue(router.display_enabled)
            self.assertTrue(router.log_enabled)
            self.assertFalse(router.show_counters)


class DefaultNameTests(unittest.TestCase):
    def test_default_name_embeds_milliseconds(self) -> None:
        self.assertEqual(
            default_logfile_name(FIXED_NOW),
            "output_2026-10-11_19-30-45-123.csv",
        )

    def test_default_name_is_in_memory_until_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            expected = Path(tmp) / "output_2026-10-11_19-30-45-123.csv"
            self.assertEqual(router.display_name(), str(expected))
            self.assertFalse(expected.exists())
            self.assertFalse(router.created)


class RecordingTests(unittest.TestCase):
    def test_shell_mode_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.record(make_hit())
            self.assertFalse(router.created)
            self.assertEqual(router.total, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_log_mode_creates_file_lazily(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_mode(OutputMode.LOG)
            self.assertFalse(router.created)
            router.record(make_hit())
            self.assertTrue(router.created)
            contents = Path(router.display_name()).read_text(encoding="utf-8")
            self.assertIn("0x0000005B", contents)

    def test_counts_per_watchpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_mode(OutputMode.LOG)
            router.record(make_hit(watchpoint=0))
            router.record(make_hit(watchpoint=0))
            router.record(make_hit(watchpoint=1))
            self.assertEqual(router.counts(), {0: 2, 1: 1})
            self.assertEqual(router.total, 3)

    def test_shell_mode_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.record(make_hit())
            self.assertEqual(router.counts(), {})


class NameResolutionTests(unittest.TestCase):
    def test_user_name_is_used_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_logfile("game.csv")
            router.set_mode(OutputMode.LOG)
            router.record(make_hit())
            self.assertEqual(Path(router.display_name()).name, "game.csv")

    def test_existing_user_name_gets_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "game.csv").touch()
            router = make_router(self, tmp)
            router.set_logfile("game.csv")
            router.set_mode(OutputMode.LOG)
            router.record(make_hit())
            self.assertEqual(Path(router.display_name()).name, "game_1.csv")

    def test_second_collision_increments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "game.csv").touch()
            Path(tmp, "game_1.csv").touch()
            router = make_router(self, tmp)
            router.set_logfile("game.csv")
            router.set_mode(OutputMode.LOG)
            router.record(make_hit())
            self.assertEqual(Path(router.display_name()).name, "game_2.csv")

    def test_set_logfile_resets_writer_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_mode(OutputMode.LOG)
            router.record(make_hit())
            self.assertEqual(router.total, 1)
            router.set_logfile("other.csv")
            self.assertFalse(router.created)
            self.assertEqual(router.total, 0)
            router.record(make_hit())
            self.assertEqual(Path(router.display_name()).name, "other.csv")

    def test_invalid_path_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_router(self, tmp)
            router.set_logfile(str(Path(tmp) / "missing" / "game.csv"))
            router.set_mode(OutputMode.LOG)
            with self.assertRaises(EventLogError):
                router.record(make_hit())


def make_aggregate_router(
    case: unittest.TestCase, tmp: str, columns: list[int]
) -> OutputRouter:
    router = OutputRouter(
        Path(tmp), now=lambda: FIXED_NOW, columns=lambda: list(columns)
    )
    case.addCleanup(router.close)
    return router


class FrameRecordingTests(unittest.TestCase):
    def test_shell_mode_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_aggregate_router(self, tmp, [1, 2])
            router.record_frame(184, {1: 0x1D, 2: 0x60})
            self.assertFalse(router.created)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_log_mode_creates_wide_file_lazily(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_aggregate_router(self, tmp, [1, 2])
            router.set_mode(OutputMode.LOG)
            self.assertFalse(router.created)
            router.record_frame(184, {1: 0x1D, 2: 0x60})
            self.assertTrue(router.created)
            lines = Path(router.display_name()).read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "timestamp,frame,wp1,wp2")
            self.assertEqual(
                lines[1], "2026-10-11T19:30:45.123,184,0x0000001D,0x00000060"
            )

    def test_counts_per_watchpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_aggregate_router(self, tmp, [1, 2])
            router.set_mode(OutputMode.LOG)
            router.record_frame(1, {1: 0x1, 2: 0x2})
            router.record_frame(2, {2: 0x3})
            self.assertEqual(router.counts(), {1: 1, 2: 2})
            self.assertEqual(router.total, 3)

    def test_kind_switch_starts_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_aggregate_router(self, tmp, [1, 2])
            router.set_mode(OutputMode.LOG)
            router.set_logfile("game.csv")
            router.record(make_hit())
            self.assertEqual(Path(router.display_name()).name, "game.csv")
            router.record_frame(184, {1: 0x1D})
            self.assertEqual(Path(router.display_name()).name, "game_1.csv")
            lines = Path(router.display_name()).read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "timestamp,frame,wp1,wp2")

    def test_invalid_path_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = make_aggregate_router(self, tmp, [1])
            router.set_logfile(str(Path(tmp) / "missing" / "frames.csv"))
            router.set_mode(OutputMode.LOG)
            with self.assertRaises(EventLogError):
                router.record_frame(1, {1: 0x1})


if __name__ == "__main__":
    unittest.main()
