from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_wrapper.app import Application
from fs_uae_debug_wrapper.config import AppConfig
from fs_uae_debug_wrapper.eventlog import EventLogError
from fs_uae_debug_wrapper.parser import DebuggerOutputParser, EventType, parse_line

HIT_LINE = "Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)"


class FakeSession:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    def alive(self) -> bool:
        return True

    def set_dimensions(self, *_args: int) -> None:
        return None

    @property
    def fd(self) -> int:
        return -1


class FakeTerminal:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data


def make_app(case: unittest.TestCase, tmp: str) -> Application:
    app = Application(AppConfig(fsuae_args=["--load_state=2", "cfg.fs-uae"]))
    app.session = FakeSession()  # type: ignore[assignment]
    app._terminal = FakeTerminal()  # type: ignore[assignment]
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
            assert isinstance(app._terminal, FakeTerminal)
            self.assertIn(b"failed to log", app._terminal.data)

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
            app._editor.buffer.extend(b"m")
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
            app._handle_line(app._terminal, b"r")  # type: ignore[arg-type]
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
            app._handle_line(app._terminal, b":status")  # type: ignore[arg-type]
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_native_command_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._handle_line(app._terminal, b"r")  # type: ignore[arg-type]
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"r\n"])

    def test_quit_sets_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._handle_line(app._terminal, b":quit")  # type: ignore[arg-type]
            self.assertTrue(app._stopping)

    def test_prompt_redrawn_after_wrapper_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._process_events([prompt_event()])
            app._handle_line(app._terminal, b":status")  # type: ignore[arg-type]
            assert isinstance(app._terminal, FakeTerminal)
            assert isinstance(app.session, FakeSession)
            self.assertTrue(app._terminal.data.endswith(b">"))
            self.assertEqual(app.session.sent, [])
            self.assertTrue(app._at_prompt)

    def test_native_command_clears_prompt_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._process_events([prompt_event()])
            app._handle_line(app._terminal, b"r")  # type: ignore[arg-type]
            self.assertFalse(app._at_prompt)


if __name__ == "__main__":
    unittest.main()
