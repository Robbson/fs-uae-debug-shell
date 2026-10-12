"""Application orchestration: the transparent shell loop."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from .aggregate import AggregatedFrame, FrameAggregator, format_frame_line
from .commands import (
    ARGUMENT_CHOICES,
    COMMANDS,
    CommandDispatcher,
    CommandResult,
)
from .config import AppConfig
from .dump import RegisterDump
from .eventlog import EventLogError
from .frames import FrameValueSelector
from .output import OutputRouter
from .parser import DebuggerOutputParser, Event, EventType, Piece, WatchpointHit
from .scenarios import WatchpointRegistry
from .session import Session, SessionError, SessionState
from .terminal import Console, WrapperCompleter

log = logging.getLogger("fs_uae_debug_shell")


class Application:
    """Wire the console, the FS-UAE session and the automation features."""

    def __init__(self, config: AppConfig, console: Console | None = None) -> None:
        self.config = config
        self.session = Session(config.executable, config.fsuae_args)
        self.parser = DebuggerOutputParser()
        self.frames = FrameValueSelector()
        self.aggregate = FrameAggregator()
        self.dump = RegisterDump()
        self.scenarios = WatchpointRegistry(config.scenarios)
        self.output = OutputRouter(
            base_dir=Path.cwd(),
            columns=self.aggregate.columns,
            labels=self.scenarios.aliases,
        )
        if console is not None:
            self.console = console
        else:
            completer = WrapperCompleter(
                config.prefix,
                COMMANDS,
                ARGUMENT_CHOICES,
                scenario_names=self.scenarios.names,
            )
            self.console = Console(completer=completer)
        self.state = SessionState.RUNNING
        self._stopping = False
        self._suppress_block = False
        self._debugger_activation_sent = False
        self._activation_timer: asyncio.TimerHandle | None = None
        self._prompt_ready = asyncio.Event()
        self._definitions: dict[int, str] = {}
        self.dispatcher = CommandDispatcher(
            prefix=config.prefix,
            output=self.output,
            frames=self.frames,
            aggregate=self.aggregate,
            scenarios=self.scenarios,
            status_provider=self._status_text,
            dump=self.dump,
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
        # The interactive prompt is raised only while the debugger is idle at
        # its ``>`` prompt, so that while emulation runs or a command's output is
        # still arriving no ``prompt_toolkit`` application is running and child
        # output is written straight to the terminal.  ``log`` mode is the
        # exception: its hit block is hidden, so there is nothing to repaint and
        # the prompt (with its status line) is kept up while emulation runs for
        # continuous counter feedback.
        while not self._stopping and self.session.alive():
            if not self._prompt_is_persistent():
                await self._prompt_ready.wait()
            if self._stopping or not self.session.alive():
                break
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

    def _prompt_is_persistent(self) -> bool:
        """Whether the prompt stays raised while the debugger is not at ``>``.

        True only in ``log`` mode, where the watchpoint hit block is hidden and
        the status line is the sole feedback; the prompt is then kept up across
        resumes so the counter never disappears.
        """

        return self.output.show_counters

    def _shutdown(self) -> None:
        self._cancel_activation_timer()
        self._flush_pending_frames()
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
        out: list[str] = []
        for piece in self.parser.feed_pieces(text):
            self._handle_piece(piece, out)
        if out:
            self.console.write("".join(out))

    def _handle_piece(self, piece: Piece, out: list[str]) -> None:
        event = piece.event
        if piece.in_dump and not self.dump.enabled:
            # Hide the CPU register dump; only the terminal view is affected.
            return
        if event is not None and event.type is EventType.WATCHPOINT_HIT:
            for emitted in self.frames.select(piece):
                self._emit_hit(emitted, out)
            display = self.output.display_enabled
            self._suppress_block = self.output.log_enabled and not display
            return
        if event is not None:
            # Any other structured event ends the current frame stream.
            self._flush_frames(out)
        if event is not None and event.type is EventType.PROMPT:
            if not self._suppress_block and piece.text != ">":
                out.append(piece.text)
            self._suppress_block = False
            self._process_events([event], out)
            return
        if self._suppress_block:
            return
        out.append(piece.text)
        if event is not None:
            self._process_events([event], out)

    def _emit_hit(self, piece: Piece, out: list[str]) -> None:
        """Display and log a selected watchpoint hit.

        With frame aggregation enabled and a frame counter present, the hit is
        buffered and emitted later as one condensed row per frame; otherwise it
        is shown and logged unchanged.
        """

        event = piece.event
        if event is None or event.hit is None:
            return
        hit = event.hit
        self.aggregate.add_columns((hit.watchpoint,))
        if self.aggregate.enabled and hit.frame is not None:
            for aggregated in self.aggregate.select(piece):
                self._emit_aggregate(aggregated, out)
            return
        self._emit_raw_hit(piece, out)

    def _emit_raw_hit(self, piece: Piece, out: list[str]) -> None:
        event = piece.event
        if event is None or event.hit is None:
            return
        if self.output.display_enabled:
            out.append(piece.text)
        self._on_hit(event.hit, out)

    def _emit_aggregate(self, aggregated: AggregatedFrame, out: list[str]) -> None:
        """Show and log one condensed frame row."""

        if self.output.display_enabled:
            line = format_frame_line(
                aggregated.frame,
                aggregated.values,
                self.aggregate.columns(),
                self.scenarios.aliases(),
            )
            out.append(line + "\n")
        if self.output.log_enabled:
            self._on_frame(aggregated, out)

    def _flush_frames(self, out: list[str]) -> None:
        for piece in self.frames.flush():
            self._emit_hit(piece, out)
        for aggregated in self.aggregate.flush():
            self._emit_aggregate(aggregated, out)

    def _flush_pending_frames(self) -> None:
        out: list[str] = []
        self._flush_frames(out)
        if out:
            self.console.write("".join(out))

    def _stop_from_child(self) -> None:
        self._stopping = True
        self._cancel_activation_timer()
        self._prompt_ready.set()
        self.console.cancel()

    def _process_events(
        self, events: list[Event], out: list[str] | None = None
    ) -> None:
        for event in events:
            if event.type is EventType.WATCHPOINT_HIT and event.hit is not None:
                self._on_hit(event.hit, out)
            elif event.type is EventType.DEBUGGER_ACTIVATED:
                self.state = SessionState.STOPPED
            elif event.type is EventType.DEBUGGER_SIGNAL_READY:
                self._activate_debugger()
            elif event.type is EventType.PROMPT:
                self.state = SessionState.STOPPED
                self._prompt_ready.set()
            elif event.type is EventType.WATCHPOINT_DEFINED and event.definition is not None:
                definition = event.definition
                self.aggregate.add_columns((definition.watchpoint,))
                self._definitions[definition.watchpoint] = (
                    f"{definition.start:08X}-{definition.end:08X} "
                    f"({definition.length}) {definition.access} {definition.scope}"
                )

    def _activate_debugger(self) -> None:
        """Enter the debugger at startup with ``--startdebug``.

        Sent once, after FS-UAE prints its signal-ready marker (an earlier
        ``SIGUSR1`` would kill the process).  Without ``--startdebug`` the
        marker is ignored and activation stays manual (F12+D).  An optional
        delay schedules the signal for later, so the emulator can finish what it
        is doing first.
        """

        if not self.config.start_debug or self._debugger_activation_sent:
            return
        self._debugger_activation_sent = True
        delay_ms = self.config.start_debug_delay_ms
        if delay_ms <= 0:
            self._send_debugger_signal()
            return
        loop = asyncio.get_running_loop()
        log.debug("activating the debugger in %d ms", delay_ms)
        self._activation_timer = loop.call_later(
            delay_ms / 1000.0, self._send_debugger_signal
        )

    def _send_debugger_signal(self) -> None:
        self._activation_timer = None
        try:
            self.session.activate_debugger()
        except SessionError as exc:
            log.error("could not activate the debugger: %s", exc)
            self._write(f"\n[wrapper] error: could not activate the debugger: {exc}\n")

    def _cancel_activation_timer(self) -> None:
        if self._activation_timer is not None:
            self._activation_timer.cancel()
            self._activation_timer = None

    def _on_hit(self, hit: WatchpointHit, out: list[str] | None = None) -> None:
        self.state = SessionState.STOPPED
        try:
            self.output.record(hit)
        except EventLogError as exc:
            log.error("%s", exc)
            message = (
                f"\n[wrapper] error: failed to log watchpoint {hit.watchpoint}: {exc}\n"
            )
            if out is None:
                self._write(message)
            else:
                out.append(message)
            return
        if self.output.log_enabled:
            self.console.refresh()

    def _on_frame(self, aggregated: AggregatedFrame, out: list[str] | None = None) -> None:
        self.state = SessionState.STOPPED
        try:
            self.output.record_frame(aggregated.frame, aggregated.values)
        except EventLogError as exc:
            log.error("%s", exc)
            message = (
                f"\n[wrapper] error: failed to log frame {aggregated.frame}: {exc}\n"
            )
            if out is None:
                self._write(message)
            else:
                out.append(message)
            return
        if self.output.log_enabled:
            self.console.refresh()

    # -- user input ----------------------------------------------------------

    def _handle_line(self, text: str) -> None:
        if self.dispatcher.handles(text):
            result: CommandResult = self.dispatcher.dispatch(text)
            self._write(f"\n[wrapper] {result.output}\n")
            if result.commands:
                # Scenario commands drive the debugger themselves; take the
                # prompt down until it prints ``>`` again, as for a forwarded
                # command.
                self._prompt_ready.clear()
                self._send_commands(result.commands)
            if result.quit:
                self._stopping = True
            return
        # Forwarding a command takes the debugger off its prompt: drop the
        # interactive prompt and re-raise it only at the next ``>``.
        self._prompt_ready.clear()
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
            f"frame values: {self.frames.mode.value}",
            f"frame aggregation: {'on' if self.aggregate.enabled else 'off'}",
            f"register dump: {'on' if self.dump.enabled else 'off'}",
        ]
        name = self.output.display_name()
        if not self.output.created:
            name = f"{name} (not created yet)"
        lines.append(f"logfile: {name}")
        lines.append(f"scenarios: {self._scenario_summary()}")
        counts = self.output.counts()
        if counts:
            lines.append(f"logged events: {self.output.total}")
            for watchpoint in sorted(counts):
                lines.append(
                    f"  {self._watchpoint_label(watchpoint)}: {counts[watchpoint]}"
                )
        if self._definitions:
            lines.append("debugger watchpoints:")
            for key in sorted(self._definitions):
                alias = self.scenarios.alias(key)
                label = f"{key} ({alias})" if alias else f"{key}"
                lines.append(f"  {label}: {self._definitions[key]}")
        return "\n".join(lines)

    def _toolbar_text(self) -> str:
        name = Path(self.output.display_name()).name
        text = f"log -> {name}  |  logged: {self.output.total}"
        counts = self.output.counts()
        if counts:
            parts = "  ".join(
                f"{self._watchpoint_label(watchpoint)}: {count}"
                for watchpoint, count in sorted(counts.items())
            )
            text += f"  |  {parts}"
        return text

    def _scenario_summary(self) -> str:
        names = self.scenarios.active_names()
        if names:
            return ", ".join(names)
        if self.scenarios.configured:
            return f"none active ({', '.join(self.scenarios.names())} available)"
        return "none"

    def _watchpoint_label(self, watchpoint: int) -> str:
        """Return the scenario alias for *watchpoint*, or ``wp<id>``."""

        alias = self.scenarios.alias(watchpoint)
        return alias if alias is not None else f"wp{watchpoint}"

    def _write(self, text: str) -> None:
        self.console.write(text)

    def _print_startup_banner(self) -> None:
        args = " ".join(self.config.fsuae_args)
        if self.config.start_debug:
            delay = self.config.start_debug_delay_ms
            if delay > 0:
                activation = (
                    f"; the debugger will be activated automatically after "
                    f"{delay} ms.\n"
                )
            else:
                activation = (
                    "; the debugger will be activated automatically at startup.\n"
                )
        else:
            activation = (
                "; activate the debugger with F12+D when the game is running.\n"
            )
        sys.stderr.write(
            "[wrapper] started FS-UAE"
            + (f" ({args})" if args else "")
            + activation
            + f"[wrapper] type '{self.config.prefix}help' at the debugger prompt "
            "for shell commands.\n"
        )
        sys.stderr.flush()
