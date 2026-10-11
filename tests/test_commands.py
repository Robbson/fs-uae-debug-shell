from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_wrapper.commands import CommandDispatcher
from fs_uae_debug_wrapper.watchpoints import WatchpointManager


def make_dispatcher(case: unittest.TestCase, tmp: str) -> tuple[CommandDispatcher, WatchpointManager]:
    manager = WatchpointManager()
    case.addCleanup(manager.close)

    def status() -> str:
        return "state: stopped"

    dispatcher = CommandDispatcher(
        prefix=":",
        manager=manager,
        status_provider=status,
        base_dir=Path(tmp),
    )
    return dispatcher, manager


class CommandDispatcherTests(unittest.TestCase):
    def test_handles_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            self.assertTrue(dispatcher.handles(":help"))
            self.assertFalse(dispatcher.handles("r"))
            self.assertFalse(dispatcher.handles("g"))

    def test_help(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":help")
            self.assertTrue(result.ok)
            self.assertIn("wrapper commands", result.output)
            self.assertIn("logwatch", result.output)

    def test_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":status")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "state: stopped")

    def test_unknown_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":bogus")
            self.assertFalse(result.ok)
            self.assertIn("unknown command", result.output)

    def test_empty_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":")
            self.assertFalse(result.ok)

    def test_logwatch_and_logoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch 0 score.csv")
            self.assertTrue(result.ok, result.output)
            self.assertIsNotNone(manager.get(0))

            result = dispatcher.dispatch(":logoff 0")
            self.assertTrue(result.ok)
            self.assertIsNone(manager.get(0))

    def test_logwatch_invalid_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch notanumber score.csv")
            self.assertFalse(result.ok)

    def test_logwatch_wrong_arity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch 0")
            self.assertFalse(result.ok)

    def test_logwatch_bad_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch 0 missing/score.csv")
            self.assertFalse(result.ok)

    def test_logoff_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logoff 9")
            self.assertFalse(result.ok)

    def test_logwatch_relative_resolves_to_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager = make_dispatcher(self, tmp)
            dispatcher.dispatch(":logwatch 1 sub.csv")
            config = manager.get(1)
            assert config is not None
            self.assertEqual(config.path, Path(tmp) / "sub.csv")

    def test_quit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":quit")
            self.assertTrue(result.quit)

    def test_quoted_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(':logwatch 0 "my log.csv"')
            self.assertTrue(result.ok, result.output)
            config = manager.get(0)
            assert config is not None
            self.assertEqual(config.path.name, "my log.csv")


if __name__ == "__main__":
    unittest.main()
