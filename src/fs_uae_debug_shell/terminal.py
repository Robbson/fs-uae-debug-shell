"""Interactive terminal input and output built on ``prompt_toolkit``."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    PathCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.patch_stdout import patch_stdout

Toolbar = Callable[[], str]


class WrapperCompleter(Completer):
    """Complete shell command names and their arguments.

    Completion only engages on lines that start with the shell prefix.  The
    first word after the prefix completes to a command name; the first argument
    completes either to a fixed set of choices (for example ``shell``/``log``/
    ``both`` for ``:output``) or to filesystem paths (for ``:logfile``).
    """

    def __init__(
        self,
        prefix: str,
        commands: Sequence[str],
        arguments: dict[str, Sequence[str]] | None = None,
    ) -> None:
        self._prefix = prefix
        self._commands = tuple(commands)
        self._arguments = dict(arguments or {})
        self._path_completer = PathCompleter()

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        before = document.text_before_cursor
        if not before.startswith(self._prefix):
            return
        body = before[len(self._prefix) :].replace("\t", " ")
        if " " in body:
            command, _, argument = body.partition(" ")
            if " " in argument:
                return
            yield from self._argument_completions(command.lower(), argument, complete_event)
            return
        for name in self._commands:
            if name.startswith(body):
                yield Completion(name, start_position=-len(body))

    def _argument_completions(
        self, command: str, argument: str, complete_event: CompleteEvent
    ):
        if command == "logfile":
            argument_document = Document(argument, len(argument))
            yield from self._path_completer.get_completions(
                argument_document, complete_event
            )
            return
        for choice in self._arguments.get(command, ()):
            if choice.startswith(argument):
                yield Completion(choice, start_position=-len(argument))


class Console:
    """Line input with editing/history, completion and safe concurrent output.

    Wraps a :class:`prompt_toolkit.PromptSession`, which provides cursor
    movement (Left/Right), Home/End, Backspace/Delete, and history navigation
    with the Up/Down arrows using its default key bindings.  Tab triggers
    completion.  Debugger output is written through :meth:`write`; while a
    prompt is active it is rendered above the input line by ``patch_stdout`` so
    it cannot corrupt what the user is typing.

    The underlying session is created lazily so that constructing a
    :class:`Console` never touches the terminal on its own.
    """

    def __init__(
        self,
        session: PromptSession[str] | None = None,
        completer: Completer | None = None,
    ) -> None:
        self._session = session
        self._completer = completer

    @property
    def session(self) -> PromptSession[str]:
        if self._session is None:
            self._session = PromptSession(completer=self._completer)
        return self._session

    @contextmanager
    def patched_stdout(self) -> Iterator[None]:
        """Render output produced while the prompt is active above it."""

        with patch_stdout(raw=True):
            yield

    async def prompt_async(
        self,
        message: str = "",
        bottom_toolbar: Toolbar | None = None,
    ) -> str:
        """Read one line of input, with editing, history and completion.

        *message* is the prompt shown before the input; *bottom_toolbar*
        renders a fixed status line below the prompt.
        """

        return await self.session.prompt_async(
            message=message, bottom_toolbar=bottom_toolbar
        )

    def refresh(self) -> None:
        """Redraw the active prompt to reflect changed status output."""

        session = self._session
        if session is None:
            return
        app = session.app
        if app is not None and app.is_running:
            app.invalidate()

    def write(self, text: str) -> None:
        """Write *text* to the terminal (above the prompt, if active)."""

        if not text:
            return
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (BrokenPipeError, ValueError):
            pass

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
