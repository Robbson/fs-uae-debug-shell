"""Interactive terminal input and output built on ``prompt_toolkit``."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout


class Console:
    """Line input with editing/history and safe concurrent output.

    Wraps a :class:`prompt_toolkit.PromptSession`, which provides cursor
    movement (Left/Right), Home/End, Backspace/Delete, and history navigation
    with the Up/Down arrows using its default key bindings.  Debugger output is
    written through :meth:`write`; while a prompt is active it is rendered
    above the input line by ``patch_stdout`` so it cannot corrupt what the user
    is typing.

    The underlying session is created lazily so that constructing a
    :class:`Console` never touches the terminal on its own.
    """

    def __init__(self, session: PromptSession[str] | None = None) -> None:
        self._session = session

    @property
    def session(self) -> PromptSession[str]:
        if self._session is None:
            self._session = PromptSession()
        return self._session

    @contextmanager
    def patched_stdout(self) -> Iterator[None]:
        """Render output produced while the prompt is active above it."""

        with patch_stdout(raw=True):
            yield

    async def prompt_async(self) -> str:
        """Read one line of input, with editing and history."""

        return await self.session.prompt_async()

    def write(self, text: str) -> None:
        """Write *text* to the terminal (above the prompt, if active)."""

        if not text:
            return
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (BrokenPipeError, ValueError):
            pass

    def input_pending(self) -> bool:
        """Return whether the user has typed an unsubmitted line."""

        session = self._session
        if session is None:
            return False
        return bool(session.default_buffer.text)

    def cancel(self) -> None:
        """Dismiss an active prompt (used when the child process exits)."""

        session = self._session
        if session is None:
            return
        app = session.app
        if app is not None and app.is_running:
            app.exit()

    @staticmethod
    def size() -> tuple[int, int]:
        """Return the terminal size as ``(rows, columns)``."""

        columns, rows = shutil.get_terminal_size((80, 24))
        return rows, columns
