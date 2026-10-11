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


def make_app(case: unittest.TestCase, tmp: str, **overrides: object) -> Application:
    console = FakeConsole()
    config = AppConfig(fsuae_args=["--load_state=2", "cfg.fs-uae"], **overrides)
    app = Application(config, console=console)  # type: ignore[arg-type]
    app.session = FakeSession()  # type: ignore[assignment]
    case.addCleanup(app.watchpoints.close)
    return app


def hit_event():
    event = parse_line(HIT_LINE)
    assert event is not None
    return event


def hit_line(value: int = 0x5B) -> str:
    return (
        f"Memwatch 0: break at 00000574.W  W  {value:08X} PC=0000C28C CPUDW (000)"
    )


def hit_with(value: int = 0x5B):
    event = parse_line(hit_line(value))
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


DUMP = (
    " -- stub -- activate_console\n"
    "  D0 00000F30   D1 00000028   D2 0000FFFF   D3 00000000\n"
    "USP  00C0BEF4 ISP  0007FFF8\n"
    "Next PC: 00008a6e\n"
)


class OutputFilteringTests(unittest.TestCase):
    def test_dump_suppressed_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn(HIT_LINE, app.console.data)
            self.assertNotIn("D0", app.console.data)
            self.assertNotIn("Next PC", app.console.data)
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"g\n"])

    def test_prompt_hidden_during_suppressed_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertFalse(app.console.data.rstrip().endswith(">"))

    def test_wrapper_summary_hidden_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertNotIn("[wrapper] watchpoint 0 ->", app.console.data)

    def test_dump_and_summary_shown_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp, show_watchpoint_dump=True)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn("D0", app.console.data)
            self.assertIn("Next PC", app.console.data)
            self.assertIn("[wrapper] watchpoint 0 ->", app.console.data)

    def test_unconfigured_hit_shows_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn("D0", app.console.data)
            self.assertIn("not logging", app.console.data)
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])

    def test_manual_activation_shows_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app._consume_output("WARNING: Activated debugger\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn("WARNING: Activated debugger", app.console.data)
            self.assertIn("D0", app.console.data)

    def test_dump_with_auto_resume_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp, auto_resume=False)
            app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))
            app._consume_output(HIT_LINE + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertIn("D0", app.console.data)
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [])


class WwclAndChangeFilterTests(unittest.TestCase):
    def _watch(self, app: Application, tmp: str) -> None:
        app.watchpoints.define_watch(0, "ball.x", 0x574, 2)
        app.watchpoints.enable(0, "score.csv", base_dir=Path(tmp))

    def _rows(self, tmp: str) -> list[str]:
        contents = (Path(tmp) / "score.csv").read_text(encoding="utf-8")
        return [line for line in contents.splitlines() if line][1:]

    def test_duplicate_hit_not_logged_but_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            self._watch(app, tmp)
            app._process_events([hit_with(0x5B), prompt_event()])
            app._process_events([hit_with(0x5B), prompt_event()])
            rows = self._rows(tmp)
            self.assertEqual(len(rows), 1)
            self.assertIn("ball.x", rows[0])
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"g\n", b"g\n"])

    def test_changed_hits_are_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            self._watch(app, tmp)
            app._process_events([hit_with(0x5B), prompt_event()])
            app._process_events([hit_with(0x5C), prompt_event()])
            app._process_events([hit_with(0x5C), prompt_event()])
            self.assertEqual(len(self._rows(tmp)), 2)

    def test_duplicate_hit_line_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            self._watch(app, tmp)
            app._consume_output(hit_line(0x5B) + "\n" + DUMP + ">")
            app._consume_output(hit_line(0x5C) + "\n" + DUMP + ">")
            app._consume_output(hit_line(0x5C) + "\n" + DUMP + ">")
            assert isinstance(app.console, FakeConsole)
            self.assertEqual(app.console.data.count("Memwatch 0: break at"), 2)

    def test_wwcl_forwards_native_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(self, tmp)
            app.dispatcher.base_dir = Path(tmp)
            app._handle_line(":wwcl #1 ball.x 574 2, #2 ball.y 576 2")
            assert isinstance(app.session, FakeSession)
            self.assertEqual(app.session.sent, [b"w 1 $574 2 W\n", b"w 2 $576 2 W\n"])
            self.assertFalse(app._at_prompt)


if __name__ == "__main__":
    unittest.main()
