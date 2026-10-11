"""Application orchestration: the transparent wrapper loop."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from .commands import CommandDispatcher, CommandResult
from .config import AppConfig
from .eventlog import EventLogError
from .parser import DebuggerOutputParser, Event, EventType, Piece, WatchpointHit
from .session import Session, SessionError, SessionState
from .terminal import Console
from .watchpoints import WatchpointManager

log = logging.getLogger("fs_uae_debug_wrapper")


class Application:
    """Wire the console, the FS-UAE session and the automation features."""

    def __init__(self, config: AppConfig, console: Console | None = None) -> None:
        self.config = config
        self.session = Session(config.executable, config.fsuae_args)
        self.parser = DebuggerOutputParser()
        self.watchpoints = WatchpointManager()
        self.console = console if console is not None else Console()
        self.auto_resume = config.auto_resume
        self.show_watchpoint_dump = config.show_watchpoint_dump
        self.state = SessionState.RUNNING
        self._pending_resume = False
        self._at_prompt = False
        self._stopping = False
        self._suppress_output = False
        self._definitions: dict[int, str] = {}
        self.dispatcher = CommandDispatcher(
            prefix=config.prefix,
            manager=self.watchpoints,
            status_provider=self._status_text,
            auto_resume_get=lambda: self.auto_resume,
            auto_resume_set=self._set_auto_resume,
            base_dir=Path.cwd(),
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
            try:
                line = await self.console.prompt_async()
            except EOFError:
                break
            except KeyboardInterrupt:
                self._forward_raw(b"\x03")
                continue
            if self._stopping:
                break
            self._handle_line(line)

    def _shutdown(self) -> None:
        self.watchpoints.close()
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
            assert event.hit is not None
            duplicate = self.watchpoints.is_duplicate(event.hit)
            if self.show_watchpoint_dump or not duplicate:
                self._write(piece.text)
            self._process_events([event])
            self._suppress_output = (
                not self.show_watchpoint_dump and self._pending_resume
            )
            return
        if event is not None and event.type is EventType.PROMPT:
            if not self._suppress_output:
                self._write(piece.text)
            self._suppress_output = False
            self._process_events([event])
            return
        if self._suppress_output:
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
                self._at_prompt = False
                self._on_hit(event.hit)
            elif event.type is EventType.DEBUGGER_ACTIVATED:
                self.state = SessionState.STOPPED
                self._at_prompt = False
                self._pending_resume = False
            elif event.type is EventType.PROMPT:
                self._at_prompt = True
                self._on_prompt()
            elif event.type is EventType.WATCHPOINT_DEFINED and event.definition is not None:
                definition = event.definition
                self._definitions[definition.watchpoint] = (
                    f"{definition.start:08X}-{definition.end:08X} "
                    f"({definition.length}) {definition.access} {definition.scope}"
                )

    def _on_hit(self, hit: WatchpointHit) -> None:
        self.state = SessionState.STOPPED
        watch = self.watchpoints.get_watch(hit.watchpoint)
        name = watch.name if watch is not None else ""
        config = self.watchpoints.get(hit.watchpoint)
        duplicate = self.watchpoints.is_duplicate(hit)
        self.watchpoints.observe(hit)

        if config is None:
            self._pending_resume = False
            self._write(
                f"\n[wrapper] watchpoint {hit.watchpoint} hit at "
                f"{hit.address:08X}.{hit.size} {hit.access} value={hit.value:08X} "
                f"pc={hit.pc:08X} (not logging; not resuming)\n"
            )
            return

        if not duplicate:
            try:
                config.writer.append(hit, name=name)
            except EventLogError as exc:
                log.error("%s", exc)
                self._write(
                    f"\n[wrapper] error: failed to log watchpoint {hit.watchpoint}: {exc}\n"
                    "[wrapper] leaving emulator stopped\n"
                )
                self._pending_resume = False
                return

        resuming = self.auto_resume
        if self.show_watchpoint_dump:
            suffix = "resuming" if resuming else "auto-resume disabled"
            note = " (unchanged)" if duplicate else ""
            self._write(
                f"\n[wrapper] watchpoint {hit.watchpoint} -> {config.path}: "
                f"addr={hit.address:08X} size={hit.size} access={hit.access} "
                f"value={hit.value:08X} pc={hit.pc:08X}{note} ({suffix})\n"
            )
        self._pending_resume = resuming

    def _on_prompt(self) -> None:
        self.state = SessionState.STOPPED
        if not self._pending_resume:
            return
        self._pending_resume = False
        if self._input_pending():
            log.warning("auto-resume skipped: user input is pending")
            self._write(
                "[wrapper] auto-resume skipped because you are typing; "
                "send 'g' to continue\n"
            )
            return
        try:
            self.session.send_bytes(b"g\n")
        except SessionError as exc:
            log.error("auto-resume failed: %s", exc)
            return
        self._at_prompt = False
        self.state = SessionState.RUNNING

    def _input_pending(self) -> bool:
        return self.console.input_pending()

    # -- user input ----------------------------------------------------------

    def _handle_line(self, text: str) -> None:
        if self.dispatcher.handles(text):
            result: CommandResult = self.dispatcher.dispatch(text)
            self._write(f"\n[wrapper] {result.output}\n")
            if result.quit:
                self._stopping = True
                return
            if result.forward:
                self._at_prompt = False
                self._pending_resume = False
                self._send_commands(result.forward)
            elif self._at_prompt:
                self._write(">")
            return
        self._at_prompt = False
        self._pending_resume = False
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
        self._at_prompt = False
        self._pending_resume = False
        try:
            self.session.send_bytes(data)
        except SessionError as exc:
            log.error("forwarding input failed: %s", exc)

    # -- helpers -------------------------------------------------------------

    def _set_auto_resume(self, enabled: bool) -> None:
        self.auto_resume = enabled

    def _status_text(self) -> str:
        lines = [
            f"state: {self.state.value}",
            f"fs-uae: {self.config.executable} {' '.join(self.config.fsuae_args)}".rstrip(),
            f"automatic resume: {'on' if self.auto_resume else 'off'}",
            f"watchpoint dump: {'on' if self.show_watchpoint_dump else 'off'}",
        ]
        configs = self.watchpoints.configs()
        if configs:
            lines.append("logging watchpoints:")
            for config in configs:
                lines.append(f"  {config.watchpoint} -> {config.path}")
        else:
            lines.append("logging watchpoints: none")
        if self._definitions:
            lines.append("debugger watchpoints:")
            for key in sorted(self._definitions):
                lines.append(f"  {key}: {self._definitions[key]}")
        return "\n".join(lines)

    def _write(self, text: str) -> None:
        self.console.write(text)

    def _print_startup_banner(self) -> None:
        args = " ".join(self.config.fsuae_args)
        sys.stderr.write(
            "[wrapper] started FS-UAE"
            + (f" ({args})" if args else "")
            + "; activate the debugger with F12+D when the game is running.\n"
            f"[wrapper] type '{self.config.prefix}help' at the debugger prompt "
            "for wrapper commands.\n"
        )
        sys.stderr.flush()
