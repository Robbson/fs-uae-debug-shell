from __future__ import annotations

import contextlib
import io
import unittest

from prompt_toolkit import PromptSession
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from fs_uae_debug_shell.terminal import Console


class ConsoleTests(unittest.TestCase):
    def test_injected_session_is_used(self) -> None:
        session = PromptSession(input=DummyInput(), output=DummyOutput())
        console = Console(session)
        self.assertIs(console.session, session)
        self.assertIsNotNone(session.history)

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

    def test_size_returns_positive_dimensions(self) -> None:
        rows, columns = Console.size()
        self.assertGreater(rows, 0)
        self.assertGreater(columns, 0)


if __name__ == "__main__":
    unittest.main()
