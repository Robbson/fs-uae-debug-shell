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
        self.typed = ""
        self.cancelled = False

    def write(self, text: str) -> None:
        self.data += text

    def input_pending(self) -> bool:
        return bool(self.typed)

    def cancel(self) -> None:
        self.cancelled = True


def make_app(case: unittest.TestCase, tmp: str) -> Application:
    console = FakeConsole()
    app = Application(
        AppConfig(fsuae_args=["--load_state=2", "cfg.fs-uae"]),
        console=console,  # type: ignore[arg-type]
    )
    app.session = FakeSession()  # type: ignore[assignment]
    case.addCleanup(app.watchpoints.close)
    return app


def hit_event():
    event = parse_line(HIT_LINE)
    assert event is not None
    return event


def prompt_event():
    events = DebuggerOutputParser().feed(">")
    assert events and events[0].type is EventType.PROMPT
    return events[0]


class ResumeDecisionTests(unittest.TestCase):
    def test_logs_and_resumes_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event()])
            self.assertTrue(app._pending_resume)
            app._process_events([prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"g\n"])
            self.assertFalse(app._pending_resume)

    def test_no_resume_without_logging_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._process_events([hit_event()])
            app._process_events([prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_logs_without_resume_when_auto_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.auto_resume = False
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event()])
            app._process_events([prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])
            contents = (Path(tmp) / "score.csv").read_text(encoding="utf-8")
            self.assertIn("0x0000005B", contents)

    def test_logging_failure_keeps_emulator_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            config = app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))

            def boom(*_args: object, **_kwargs: object) -> None:
                raise EventLogError("disk full")

            config.writer.append = boom  # type: ignore[assignment]
            app._process_events([hit_event()])
            app._process_events([prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])
            assert isinstance(app.console, FakeConsole)
            self.assertIn("failed to log", app.console.data)

    def test_manual_activation_does_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            activation = parse_line("WARNING: Activated debugger")
            app._process_events([activation, prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_resume_skipped_while_user_is_typing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event()])
            assert isinstance(app.console, FakeConsole)
            app.console.typed = "m"
            app._process_events([prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_consecutive_hits_resume_once_each(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event(), prompt_event()])
            app._process_events([hit_event(), prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"g\n", b"g\n"])

    def test_user_command_cancels_pending_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._process_events([hit_event()])
            self.assertTrue(app._pending_resume)
            app._handle_line("r")
            self.assertFalse(app._pending_resume)
            app._process_events([prompt_event()])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"r\n"])

    def test_status_reports_watchpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(5, "five.csv", base_dir=Path(tmp))
            app._process_events([parse_line(" 0: 00000574 - 00000575 (2)  W  CPU")])
            text = app._status_text()
            self.assertIn("5 -> ", text)
            self.assertIn("automatic resume: on", text)


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
