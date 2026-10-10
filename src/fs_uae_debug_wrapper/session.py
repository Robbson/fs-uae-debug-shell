"""Ownership of the FS-UAE child process and debugger session state."""

from __future__ import annotations

import os
from enum import Enum

import pexpect


class SessionError(RuntimeError):
    """Raised when the FS-UAE process cannot be started."""


class SessionState(Enum):
    """High-level state of the emulated session.

    ``RUNNING`` means execution is in progress (debugger inactive or resumed);
    ``STOPPED`` means the debugger console is at its prompt; ``CLOSED`` means
    the child process is gone.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    CLOSED = "closed"


class Session:
    """Launch and talk to a single FS-UAE process through a PTY."""

    def __init__(self, executable: str, args: list[str]) -> None:
        self.executable = executable
        self.args = list(args)
        self.child: pexpect.spawn | None = None
        self.state = SessionState.RUNNING

    def start(self, dimensions: tuple[int, int] | None = None) -> None:
        """Spawn FS-UAE.  Raises :class:`SessionError` on failure."""

        if self.child is not None:
            raise SessionError("session already started")
        try:
            self.child = pexpect.spawn(
                self.executable,
                self.args,
                encoding=None,
                echo=False,
                timeout=None,
                dimensions=dimensions,
            )
        except FileNotFoundError as exc:
            raise SessionError(
                f"FS-UAE executable not found: '{self.executable}'"
            ) from exc
        except OSError as exc:
            raise SessionError(f"cannot start FS-UAE: {exc}") from exc

    @property
    def fd(self) -> int:
        if self.child is None:
            raise SessionError("session not started")
        return self.child.child_fd

    def alive(self) -> bool:
        return self.child is not None and self.child.isalive()

    def send_bytes(self, data: bytes) -> None:
        """Write raw bytes to the child's console."""

        if self.child is None:
            raise SessionError("session not started")
        if not data:
            return
        try:
            os.write(self.child.child_fd, data)
        except OSError as exc:
            raise SessionError(f"cannot write to FS-UAE: {exc}") from exc

    def send_line(self, text: str) -> None:
        """Send a single console command terminated by a newline."""

        self.send_bytes(text.encode("utf-8", errors="replace") + b"\n")

    def set_dimensions(self, rows: int, columns: int) -> None:
        if self.child is None:
            return
        try:
            self.child.setwinsize(rows, columns)
        except OSError:
            pass

    def close(self) -> None:
        """Terminate the child process and release the PTY."""

        child = self.child
        self.child = None
        self.state = SessionState.CLOSED
        if child is None:
            return
        try:
            if child.isalive():
                child.close(force=True)
            else:
                child.close()
        except OSError:
            pass
