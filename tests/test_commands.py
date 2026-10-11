from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_shell.commands import CommandDispatcher
from fs_uae_debug_shell.frames import FrameValueSelector
from fs_uae_debug_shell.output import OutputMode, OutputRouter


def make_dispatcher(case: unittest.TestCase, tmp: str) -> tuple[CommandDispatcher, OutputRouter]:
    router = OutputRouter(Path(tmp))
    case.addCleanup(router.close)

    def status() -> str:
        return "state: stopped"

    dispatcher = CommandDispatcher(
        prefix=":",
        output=router,
        frames=FrameValueSelector(),
        status_provider=status,
    )
    return dispatcher, router


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
            self.assertIn("shell commands", result.output)
            self.assertIn("output", result.output)
            self.assertIn("logfile", result.output)
            self.assertIn("framevalues", result.output)

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

    def test_output_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "output: shell")

    def test_output_sets_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            for value in ("log", "both", "shell"):
                result = dispatcher.dispatch(f":output {value}")
                self.assertTrue(result.ok, result.output)
                self.assertIs(router.mode, OutputMode(value))

    def test_output_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output BOTH")
            self.assertTrue(result.ok)
            self.assertIs(router.mode, OutputMode.BOTH)

    def test_output_invalid_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output screen")
            self.assertFalse(result.ok)

    def test_output_too_many_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output log both")
            self.assertFalse(result.ok)

    def test_logfile_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logfile")
            self.assertTrue(result.ok)
            self.assertIn("output_", result.output)
            self.assertIn(".csv", result.output)

    def test_logfile_sets_name_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logfile game.csv")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(Path(tmp, "game.csv").exists(), False)
            self.assertFalse(router.created)

    def test_logfile_quoted_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(':logfile "my log.csv"')
            self.assertTrue(result.ok, result.output)
            self.assertTrue(router.display_name().endswith("my log.csv"))

    def test_logfile_wrong_arity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logfile a.csv b.csv")
            self.assertFalse(result.ok)

    def test_framevalues_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "frame values: first")

    def test_framevalues_sets_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            for value in ("last", "all", "first"):
                result = dispatcher.dispatch(f":framevalues {value}")
                self.assertTrue(result.ok, result.output)
                self.assertEqual(dispatcher.frames.mode.value, value)

    def test_framevalues_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues ALL")
            self.assertTrue(result.ok)
            self.assertEqual(dispatcher.frames.mode.value, "all")

    def test_framevalues_invalid_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues sometimes")
            self.assertFalse(result.ok)

    def test_framevalues_too_many_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues first last")
            self.assertFalse(result.ok)

    def test_quit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":quit")
            self.assertTrue(result.quit)


if __name__ == "__main__":
    unittest.main()
