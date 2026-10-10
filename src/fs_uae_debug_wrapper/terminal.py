"""POSIX terminal handling for interactive, transparent forwarding."""

from __future__ import annotations

import os
import shutil
import sys
import termios
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

# Characters that terminate a user input line.
_BACKSPACE = (8, 127)
_CTRL_C = 3
_CTRL_D = 4


class Terminal:
    """Put the controlling terminal into raw input mode.

    Input is delivered byte-for-byte (no line discipline, no echo, no
    signals) so the wrapper can echo and route input itself.  Output
    post-processing (``OPOST``/``ONLCR``) is kept enabled so wrapper messages
    and the debugger output are displayed with correct line breaks.
    """

    def __init__(self) -> None:
        self.fd = sys.stdin.fileno()
        self._out = sys.stdout.buffer
        self._saved: list | None = None

    def __enter__(self) -> Self:
        self._saved = termios.tcgetattr(self.fd)
        raw = termios.tcgetattr(self.fd)
        raw[0] &= ~(
            termios.BRKINT
            | termios.ICRNL
            | termios.INPCK
            | termios.ISTRIP
            | termios.IXON
        )
        raw[1] |= termios.OPOST | termios.ONLCR
        raw[2] |= termios.CS8
        raw[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
        raw[6][termios.VMIN] = 1
        raw[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSAFLUSH, raw)
        return self

    def __exit__(self, *exc: object) -> bool:
        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            self._saved = None
        return False

    def read(self, size: int = 4096) -> bytes:
        return os.read(self.fd, size)

    def write(self, data: bytes) -> None:
        if not data:
            return
        try:
            self._out.write(data)
            self._out.flush()
        except (BrokenPipeError, ValueError):
            pass

    @staticmethod
    def size() -> tuple[int, int]:
        """Return the terminal size as ``(rows, columns)``."""

        columns, rows = shutil.get_terminal_size((80, 24))
        return rows, columns


@dataclass
class InputEvent:
    """A decoded unit of user input."""

    kind: str  # "line" or "raw"
    data: bytes


class LineEditor:
    """Turn raw keystrokes into complete lines with local echo.

    Backspace and Ctrl-C/Ctrl-D are handled locally; everything else is
    buffered until a newline.  The completed line is returned without the
    line terminator so the caller can decide whether it is a wrapper command.
    """

    def __init__(self) -> None:
        self.buffer = bytearray()
        self._last_was_cr = False

    @property
    def pending(self) -> bool:
        return bool(self.buffer)

    def clear(self) -> None:
        self.buffer.clear()

    def feed(self, data: bytes, echo: Callable[[bytes], None]) -> list[InputEvent]:
        events: list[InputEvent] = []
        for byte in data:
            if byte == 13:
                echo(b"\r\n")
                events.append(InputEvent("line", bytes(self.buffer)))
                self.buffer.clear()
                self._last_was_cr = True
            elif byte == 10 and self._last_was_cr:
                self._last_was_cr = False
            elif byte == 10:
                echo(b"\r\n")
                events.append(InputEvent("line", bytes(self.buffer)))
                self.buffer.clear()
            elif byte in _BACKSPACE:
                self._last_was_cr = False
                if self.buffer:
                    self.buffer.pop()
                    echo(b"\b \b")
            elif byte == _CTRL_C:
                self._last_was_cr = False
                echo(b"^C\r\n")
                self.buffer.clear()
                events.append(InputEvent("raw", bytes([byte])))
            elif byte == _CTRL_D:
                self._last_was_cr = False
                events.append(InputEvent("raw", bytes([byte])))
            elif 32 <= byte < 127:
                self._last_was_cr = False
                self.buffer.append(byte)
                echo(bytes([byte]))
            else:
                self._last_was_cr = False
        return events
