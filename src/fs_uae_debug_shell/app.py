"""Application orchestration: the transparent shell loop."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from .commands import (
    ARGUMENT_CHOICES,
    COMMANDS,
    CommandDispatcher,
    CommandResult,
)
from .config import AppConfig
from .eventlog import EventLogError
from .output import OutputRouter
from .parser import DebuggerOutputParser, Event, EventType, Piece, WatchpointHit
from .session import Session, SessionError, SessionState
from .terminal import Console, WrapperCompleter

log = logging.getLogger("fs_uae_debug_shell")


class Application:
    """Wire the console, the FS-UAE session and the automation features."""

    def __init__(self, config: AppConfig, console: Console | None = None) -> None:
        self.config = config
        self.session = Session(config.executable, config.fsuae_args)
        self.parser = DebuggerOutputParser()
        self.output = OutputRouter(base_dir=Path.cwd())
        if console is not None:
            self.console = console
        else:
            completer = WrapperCompleter(config.prefix, COMMANDS, ARGUMENT_CHOICES)
            self.console = Console(completer=completer)
        self.state = SessionState.RUNNING
        self._stopping = False
        self._suppress_block = False
        self._definitions: dict[int, str] = {}
        self.dispatcher = CommandDispatcher(
            prefix=config.prefix,
            output=self.output,
            status_provider=self._status_text,
        )

    # -- lifecycle -----------------------------------------------------------

    def run(self) -> int:
        try:
            return asyncio.run(self._run_async())
        except KeyboardInterrupt:
            return 0

    async def _run_async(self) -> int:
        try:
            self.session.start(dimensions=Console.size())
        except SessionError as exc:
            log.error("%s", exc)
            return 2

        self._print_startup_banner()
        loop = asyncio.get_running_loop()
        loop.add_reader(self.session.fd, self._on_child_readable)
        try:
            with self.console.patched_stdout():
                await self._input_loop()
        finally:
            try:
                loop.remove_reader(self.session.fd)
            except (OSError, ValueError):
                pass
            self._shutdown()
        return 0

    async def _input_loop(self) -> None:
        while not self._stopping and self.session.alive():
            self.session.set_dimensions(*Console.size())
            toolbar = self._toolbar_text if self.output.show_counters else None
            try:
                line = await self.console.prompt_async(
                    message="> ", bottom_toolbar=toolbar
                )
            except EOFError:
                break
            except KeyboardInterrupt:
                self._forward_raw(b"\x03")
                continue
            if self._stopping:
                break
            self._handle_line(line)

    def _shutdown(self) -> None:
        self.output.close()
        self.session.close()

    # -- child output --------------------------------------------------------

    def _on_child_readable(self) -> None:
        if self._stopping:
            return
        try:
            fd = self.session.fd
        except SessionError:
            self._stop_from_child()
            return
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._stop_from_child()
            return
        text = data.decode("latin-1")
        self._consume_output(text)

    def _consume_output(self, text: str) -> None:
        for piece in self.parser.feed_pieces(text):
            self._handle_piece(piece)

    def _handle_piece(self, piece: Piece) -> None:
        event = piece.event
        if event is not None and event.type is EventType.WATCHPOINT_HIT:
            display = self.output.display_enabled
            if display:
                self._write(piece.text)
            self._process_events([event])
            self._suppress_block = self.output.log_enabled and not display
            return
        if event is not None and event.type is EventType.PROMPT:
            if not self._suppress_block and piece.text != ">":
                self._write(piece.text)
            self._suppress_block = False
            self._process_events([event])
            return
        if self._suppress_block:
            return
        self._write(piece.text)
        if event is not None:
            self._process_events([event])

    def _stop_from_child(self) -> None:
        self._stopping = True
        self.console.cancel()

    def _process_events(self, events: list[Event]) -> None:
        for event in events:
            if event.type is EventType.WATCHPOINT_HIT and event.hit is not None:
                self._on_hit(event.hit)
            elif event.type is EventType.DEBUGGER_ACTIVATED:
                self.state = SessionState.STOPPED
            elif event.type is EventType.WATCHPOINT_DEFINED and event.definition is not None:
                definition = event.definition
                self._definitions[definition.watchpoint] = (
                    f"{definition.start:08X}-{definition.end:08X} "
                    f"({definition.length}) {definition.access} {definition.scope}"
                )

    def _on_hit(self, hit: WatchpointHit) -> None:
        self.state = SessionState.STOPPED
        try:
            self.output.record(hit)
        except EventLogError as exc:
            log.error("%s", exc)
            self._write(
                f"\n[wrapper] error: failed to log watchpoint {hit.watchpoint}: {exc}\n"
            )
            return
        if self.output.log_enabled:
            self.console.refresh()

    # -- user input ----------------------------------------------------------

    def _handle_line(self, text: str) -> None:
        if self.dispatcher.handles(text):
            result: CommandResult = self.dispatcher.dispatch(text)
            self._write(f"\n[wrapper] {result.output}\n")
            if result.quit:
                self._stopping = True
            return
        self._send_commands((text,))

    def _send_commands(self, commands: tuple[str, ...]) -> None:
        for command in commands:
            try:
                self.session.send_bytes(
                    command.encode("utf-8", errors="replace") + b"\n"
                )
            except SessionError as exc:
                log.error("forwarding command failed: %s", exc)

    def _forward_raw(self, data: bytes) -> None:
        try:
            self.session.send_bytes(data)
        except SessionError as exc:
            log.error("forwarding input failed: %s", exc)

    # -- helpers -------------------------------------------------------------

    def _status_text(self) -> str:
        args = " ".join(self.config.fsuae_args)
        lines = [
            f"state: {self.state.value}",
            f"fs-uae: {self.config.executable} {args}".rstrip(),
            f"output: {self.output.mode.value}",
        ]
        name = self.output.display_name()
        if not self.output.created:
            name = f"{name} (not created yet)"
        lines.append(f"logfile: {name}")
        counts = self.output.counts()
        if counts:
            lines.append(f"logged events: {self.output.total}")
            for watchpoint in sorted(counts):
                lines.append(f"  wp{watchpoint}: {counts[watchpoint]}")
        if self._definitions:
            lines.append("debugger watchpoints:")
            for key in sorted(self._definitions):
                lines.append(f"  {key}: {self._definitions[key]}")
        return "\n".join(lines)

    def _toolbar_text(self) -> str:
        name = Path(self.output.display_name()).name
        text = f"log -> {name}  |  logged: {self.output.total}"
        counts = self.output.counts()
        if counts:
            parts = "  ".join(
                f"wp{watchpoint}: {count}"
                for watchpoint, count in sorted(counts.items())
            )
            text += f"  |  {parts}"
        return text

    def _write(self, text: str) -> None:
        self.console.write(text)

    def _print_startup_banner(self) -> None:
        args = " ".join(self.config.fsuae_args)
        sys.stderr.write(
            "[wrapper] started FS-UAE"
            + (f" ({args})" if args else "")
            + "; activate the debugger with F12+D when the game is running.\n"
            f"[wrapper] type '{self.config.prefix}help' at the debugger prompt "
            "for shell commands.\n"
        )
        sys.stderr.flush()
