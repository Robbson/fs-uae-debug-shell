from __future__ import annotations

import contextlib
import io
import unittest

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from fs_uae_debug_shell.commands import ARGUMENT_CHOICES, COMMANDS
from fs_uae_debug_shell.terminal import Console, WrapperCompleter


def complete(text: str) -> list[str]:
    completer = WrapperCompleter(":", COMMANDS, ARGUMENT_CHOICES)
    document = Document(text, len(text))
    event = CompleteEvent()
    return [c.text for c in completer.get_completions(document, event)]


def complete_full(text: str) -> list[str]:
    """Return the full line produced by each completion."""

    completer = WrapperCompleter(":", COMMANDS, ARGUMENT_CHOICES)
    document = Document(text, len(text))
    event = CompleteEvent()
    return [
        text[: len(text) + c.start_position] + c.text
        for c in completer.get_completions(document, event)
    ]


def complete_scenarios(text: str, names: list[str]) -> list[str]:
    completer = WrapperCompleter(
        ":", COMMANDS, ARGUMENT_CHOICES, scenario_names=lambda: list(names)
    )
    document = Document(text, len(text))
    event = CompleteEvent()
    return [c.text for c in completer.get_completions(document, event)]


class WrapperCompleterTests(unittest.TestCase):
    def test_no_completion_without_prefix(self) -> None:
        self.assertEqual(complete("st"), [])

    def test_command_prefix_completion(self) -> None:
        self.assertIn("status", complete(":st"))
        self.assertIn("output", complete(":o"))
        self.assertIn("logfile", complete(":log"))

    def test_command_completion_is_exclusive(self) -> None:
        self.assertEqual(complete(":outp"), ["output"])

    def test_output_argument_choices(self) -> None:
        self.assertEqual(complete(":output "), ["shell", "log", "both"])

    def test_output_argument_narrowing(self) -> None:
        self.assertEqual(complete(":output l"), ["log"])

    def test_framevalues_command_completion(self) -> None:
        self.assertIn("framevalues", complete(":fra"))

    def test_framevalues_argument_choices(self) -> None:
        self.assertEqual(complete(":framevalues "), ["first", "last", "all"])

    def test_no_argument_completion_for_no_argument_command(self) -> None:
        self.assertEqual(complete(":help "), [])

    def test_sci_subcommand_completion(self) -> None:
        self.assertIn("add", complete(":sci a"))
        self.assertEqual(complete(":sci r"), ["rm"])

    def test_sci_scenario_completion(self) -> None:
        self.assertEqual(
            complete_scenarios(":sci add ", ["ball", "player1"]),
            ["*", "ball", "player1"],
        )

    def test_sci_scenario_narrowing(self) -> None:
        self.assertEqual(complete_scenarios(":sci add ba", ["ball", "player1"]), ["ball"])

    def test_sci_remove_scenario_completion(self) -> None:
        self.assertEqual(complete_scenarios(":sci rm ", ["ball"]), ["*", "ball"])

    def test_logfile_completes_paths(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "alpha.csv").write_text("", encoding="utf-8")
            results = complete_full(f":logfile {tmp}/a")
            self.assertIn(f":logfile {tmp}/alpha.csv", results)


class ConsoleTests(unittest.TestCase):
    def test_injected_session_is_used(self) -> None:
        session = PromptSession(input=DummyInput(), output=DummyOutput())
        console = Console(session)
        self.assertIs(console.session, session)
        self.assertIsNotNone(session.history)

    def test_constructed_session_gets_completer(self) -> None:
        completer = WrapperCompleter(":", COMMANDS, ARGUMENT_CHOICES)
        console = Console(completer=completer)
        self.assertIs(console.session.completer, completer)

    def test_write_to_stdout(self) -> None:
        console = Console()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            console.write("hello")
        self.assertEqual(stream.getvalue(), "hello")

    def test_write_empty_is_noop(self) -> None:
        console = Console()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            console.write("")
        self.assertEqual(stream.getvalue(), "")

    def test_cancel_without_session_is_noop(self) -> None:
        Console().cancel()

    def test_refresh_without_session_is_noop(self) -> None:
        Console().refresh()

    def test_size_returns_positive_dimensions(self) -> None:
        rows, columns = Console.size()
        self.assertGreater(rows, 0)
        self.assertGreater(columns, 0)


if __name__ == "__main__":
    unittest.main()
