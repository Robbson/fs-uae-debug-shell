from __future__ import annotations

import signal
import types
import unittest
from unittest import mock

from fs_uae_debug_shell.session import Session, SessionError


class ActivateDebuggerTests(unittest.TestCase):
    def make_session(self) -> Session:
        session = Session("fs-uae", [])
        session.child = types.SimpleNamespace(pid=4242)  # type: ignore[assignment]
        return session

    def test_sends_sigusr1_to_child(self) -> None:
        session = self.make_session()
        with mock.patch("fs_uae_debug_shell.session.os.kill") as kill:
            session.activate_debugger()
        kill.assert_called_once_with(4242, signal.SIGUSR1)

    def test_without_child_raises(self) -> None:
        with self.assertRaises(SessionError):
            Session("fs-uae", []).activate_debugger()

    def test_os_error_is_reported(self) -> None:
        session = self.make_session()
        with (
            mock.patch(
                "fs_uae_debug_shell.session.os.kill", side_effect=OSError("nope")
            ),
            self.assertRaises(SessionError),
        ):
            session.activate_debugger()


if __name__ == "__main__":
    unittest.main()
