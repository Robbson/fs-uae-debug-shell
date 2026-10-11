from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_wrapper.app import Application
from fs_uae_debug_wrapper.config import AppConfig
from fs_uae_debug_wrapper.eventlog import EventLogError
from fs_uae_debug_wrapper.parser import DebuggerOutputParser, EventType, parse_line
from fs_uae_debug_wrapper.session import SessionState

HIT_LINE = "Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)"


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

    def write(self, text: str) -> None:
        self.data += text

    def cancel(self) -> None:
        self.cancelled = True


def make_app(case: unittest.TestCase, tmp: str, **overrides: object) -> Application:
    console = FakeConsole()
    config = AppConfig(fsuae_args=["--load_state=2", "cfg.fs-uae"], **overrides)
    app = Application(config, console=console)  # type: ignore[arg-type]
    app.session = FakeSession()  # type: ignore[assignment]
    case.addCleanup(app.watchpoints.close)
    return app


def hit_event(value: int = 0x5B):
    line = (
        f"Memwatch 0: break at 00000574.W  W  {value:08X} PC=0000C28C CPUDW (000)"
    )
    event = parse_line(line)
    assert event is not None
    return event


def prompt_event():
    events = DebuggerOutputParser().feed(">")
    assert events and events[0].type is EventType.PROMPT
    return events[0]


class HitHandlingTests(unittest.TestCase):
    def test_hit_logged_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event()])
            contents = (Path(tmp) / "score.csv").read_text(encoding="utf-8")
            self.assertIn("0x0000005B", contents)

    def test_hit_does_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event(), prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_unconfigured_hit_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._process_events([hit_event()])
            assert isinstance(app.console, FakeConsole)
            self.assertIn("not logging", app.console.data)

    def test_logging_failure_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            config = app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))

            def boom(*_args: object, **_kwargs: object) -> None:
                raise EventLogError("disk full")

            config.writer.append = boom  # type: ignore[assignment]
            app._process_events([hit_event()])
            assert isinstance(app.console, FakeConsole)
            self.assertIn("failed to log", app.console.data)

    def test_status_reports_watchpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(5, "five.csv", base_dir=Path(tmp))
            app._process_events([parse_line(" 0: 00000574 - 00000575 (2)  W  CPU")])
            text = app._status_text()
            self.assertIn("5 -> ", text)

    def test_child_output_shows_full_debugger_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            dump = (
                " -- stub -- activate_console\n"
                "  D0 00000F30   D1 00000028   D2 0000FFFF   D3 00000000\n"
                "Next PC: 00008a6e\n"
            )
            app._consume_output(HIT_LINE + "\n" + dump + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn(HIT_LINE, app.console.data)
            self.assertIn("D0", app.console.data)
            self.assertIn("Next PC", app.console.data)
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

    def test_prompt_redrawn_after_wrapper_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._process_events([prompt_event()])
            app._handle_line(":status")
            assert isinstance(app.console, FakeConsole)
            assert isinstance(app.session, FakeSession)
            self.assertTrue(app.console.data.endswith(">"))
            self.assertEqual(app.session.sent, [])
            self.assertTrue(app._at_prompt)

    def test_native_command_clears_prompt_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._process_events([prompt_event()])
            app._handle_line("r")
            self.assertFalse(app._at_prompt)

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
