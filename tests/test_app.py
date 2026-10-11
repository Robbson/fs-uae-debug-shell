from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_shell.app import Application
from fs_uae_debug_shell.config import AppConfig
from fs_uae_debug_shell.output import OutputMode
from fs_uae_debug_shell.parser import DebuggerOutputParser, EventType, parse_line
from fs_uae_debug_shell.session import SessionState

HIT_LINE = "Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)"
ENHANCED_HIT_LINE = (
    "00000025 Memwatch 01: 00000574.W  W  000000AB PC=00001234 CPUDW (000)"
)
DUMP = (
    " -- stub -- activate_console\n"
    "  D0 00000F30   D1 00000028   D2 0000FFFF   D3 00000000\n"
    "Next PC: 00008a6e\n"
)


class FakeSession:
    def __init__(self, fd: int = -1) -> None:
        self.sent: list[bytes] = []
        self._fd = fd

    def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    def alive(self) -> bool:
        return True

    def set_dimensions(self, *_args: int) -> None:
        return None

    @property
    def fd(self) -> int:
        return self._fd


class FakeConsole:
    def __init__(self) -> None:
        self.data = ""
        self.cancelled = False
        self.refreshed = False

    def write(self, text: str) -> None:
        self.data += text

    def cancel(self) -> None:
        self.cancelled = True

    def refresh(self) -> None:
        self.refreshed = True


def make_app(case: unittest.TestCase, tmp: str, **overrides: object) -> Application:
    console = FakeConsole()
    config = AppConfig(fsuae_args=["--load_state=2", "cfg.fs-uae"], **overrides)
    app = Application(config, console=console)  # type: ignore[arg-type]
    app.session = FakeSession()  # type: ignore[assignment]
    app.output.set_logfile(str(Path(tmp) / "game.csv"))
    case.addCleanup(app.output.close)
    return app


def hit_event(value: int = 0x5B):
    line = f"Memwatch 0: break at 00000574.W  W  {value:08X} PC=0000C28C CPUDW (000)"
    event = parse_line(line)
    assert event is not None
    return event


def prompt_event():
    events = DebuggerOutputParser().feed(">")
    assert events and events[0].type is EventType.PROMPT
    return events[0]


class OutputRoutingTests(unittest.TestCase):
    def test_shell_mode_shows_hit_and_does_not_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn("Memwatch", app.console.data)
            self.assertIn("D0", app.console.data)
            self.assertEqual(app.output.total, 0)
            self.assertFalse((Path(tmp) / "game.csv").exists())

    def test_log_mode_hides_block_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.LOG)
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertEqual(app.console.data, "")
            self.assertEqual(app.output.total, 1)
            contents = (Path(tmp) / "game.csv").read_text(encoding="utf-8")
            self.assertIn("0x0000005B", contents)

    def test_enhanced_hit_logged_and_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.LOG)
            app._consume_output(ENHANCED_HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertEqual(app.console.data, "")
            contents = (Path(tmp) / "game.csv").read_text(encoding="utf-8")
            self.assertIn("0x000000AB", contents)
            row = contents.splitlines()[1].split(",")
            self.assertEqual(row[1], "25")
            self.assertEqual(app.output.total, 1)

    def test_enhanced_hit_shown_in_shell_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._consume_output(ENHANCED_HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn(ENHANCED_HIT_LINE, app.console.data)
            self.assertEqual(app.output.total, 0)

    def test_both_mode_shows_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.BOTH)
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn("Memwatch", app.console.data)
            self.assertIn("D0", app.console.data)
            self.assertEqual(app.output.total, 1)

    def test_log_mode_refreshes_status_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.LOG)
            app._process_events([hit_event()])
            assert isinstance(app.console, FakeConsole)
            self.assertTrue(app.console.refreshed)

    def test_logging_failure_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.LOG)
            app.output.set_logfile(str(Path(tmp) / "missing" / "game.csv"))
            app._process_events([hit_event()])
            assert isinstance(app.console, FakeConsole)
            self.assertIn("failed to log", app.console.data)

    def test_toolbar_counts_per_watchpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.LOG)
            app._process_events([hit_event(), hit_event()])
            text = app._toolbar_text()
            self.assertIn("logged: 2", text)
            self.assertIn("wp0: 2", text)

    def test_counter_line_only_in_log_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            self.assertFalse(app.output.show_counters)
            app.output.set_mode(OutputMode.LOG)
            self.assertTrue(app.output.show_counters)
            app.output.set_mode(OutputMode.BOTH)
            self.assertFalse(app.output.show_counters)

    def test_status_reports_output_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.BOTH)
            app._process_events(
                [hit_event(), parse_line(" 0: 00000574 - 00000575 (2)  W  CPU")]
            )
            text = app._status_text()
            self.assertIn("output: both", text)
            self.assertIn("logged events: 1", text)
            self.assertIn("game.csv", text)
            self.assertIn("debugger watchpoints:", text)

    def test_hit_does_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.output.set_mode(OutputMode.BOTH)
            app._process_events([hit_event(), prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])


class InputHandlingTests(unittest.TestCase):
    def test_wrapper_command_not_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._handle_line(":status")
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_native_command_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._handle_line("r")
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"r\n"])

    def test_quit_sets_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._handle_line(":quit")
            self.assertTrue(app._stopping)

    def test_child_prompt_is_not_echoed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._consume_output("Next PC: 00008a6e\n>")
            assert isinstance(app.console, FakeConsole)
            self.assertNotIn(">", app.console.data)
            self.assertIn("Next PC", app.console.data)

    def test_raw_input_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._forward_raw(b"\x03")
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"\x03"])

    def test_child_close_stops_and_cancels_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._stop_from_child()
            self.assertTrue(app._stopping)
            assert isinstance(app.console, FakeConsole)
            self.assertTrue(app.console.cancelled)


class ChildReaderTests(unittest.TestCase):
    def test_child_output_forwarded_and_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            read_fd, write_fd = os.pipe()
            self.addCleanup(os.close, read_fd)
            self.addCleanup(os.close, write_fd)
            assert isinstance(app.session, FakeSession)
            app.session._fd = read_fd
            os.write(write_fd, (HIT_LINE + "\n").encode("latin-1"))
            app._on_child_readable()
            assert isinstance(app.console, FakeConsole)
            self.assertIn(HIT_LINE, app.console.data)
            self.assertEqual(app.state, SessionState.STOPPED)

    def test_child_eof_stops_and_cancels_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            read_fd, write_fd = os.pipe()
            self.addCleanup(os.close, read_fd)
            assert isinstance(app.session, FakeSession)
            app.session._fd = read_fd
            os.close(write_fd)
            app._on_child_readable()
            self.assertTrue(app._stopping)
            assert isinstance(app.console, FakeConsole)
            self.assertTrue(app.console.cancelled)

    def test_reader_ignored_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._stopping = True
            app._on_child_readable()
            assert isinstance(app.console, FakeConsole)
            self.assertEqual(app.console.data, "")


if __name__ == "__main__":
    unittest.main()
