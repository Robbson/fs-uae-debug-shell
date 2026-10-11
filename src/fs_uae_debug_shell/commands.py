"""Shell-specific commands, prefixed to keep them out of the FS-UAE namespace."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass

from .aggregate import FrameAggregator
from .frames import FrameValueMode, FrameValueSelector
from .output import OutputMode, OutputRouter


class UsageError(Exception):
    """Raised for malformed shell command arguments."""


@dataclass
class CommandResult:
    """Outcome of a shell command."""

    output: str = ""
    ok: bool = True
    quit: bool = False


HELP_TEXT = """\
shell commands (prefix '{prefix}'):
  {prefix}help                       show this help
  {prefix}status                     show debugger state, output mode and log file
  {prefix}output shell|log|both      route watchpoint hits (default: shell)
  {prefix}logfile <file>             set the CSV log file name
  {prefix}framevalues first|last|all keep which hit per frame and watchpoint
                                     (default: first; ignored without a frame counter)
  {prefix}frameagg on|off            condense each frame into one row of
                                     watchpoint values (default: on)
  {prefix}quit                       stop the emulator and exit the shell
All other input is forwarded to the FS-UAE debugger unchanged."""

COMMANDS = ("help", "status", "output", "logfile", "framevalues", "frameagg", "quit")
ARGUMENT_CHOICES: dict[str, tuple[str, ...]] = {
    "output": ("shell", "log", "both"),
    "framevalues": ("first", "last", "all"),
    "frameagg": ("on", "off"),
}


class CommandDispatcher:
    """Dispatch lines beginning with the shell prefix."""

    def __init__(
        self,
        *,
        prefix: str,
        output: OutputRouter,
        frames: FrameValueSelector,
        aggregate: FrameAggregator,
        status_provider: Callable[[], str],
    ) -> None:
        self.prefix = prefix
        self.output = output
        self.frames = frames
        self.aggregate = aggregate
        self._status_provider = status_provider

    def handles(self, line: str) -> bool:
        return line.startswith(self.prefix)

    def dispatch(self, line: str) -> CommandResult:
        body = line[len(self.prefix) :].strip()
        if not body:
            return CommandResult(
                output=f"error: empty shell command; try '{self.prefix}help'",
                ok=False,
            )
        name, _, rest = body.partition(" ")
        name = name.lower()
        try:
            args = shlex.split(rest) if rest.strip() else []
        except ValueError as exc:
            return CommandResult(output=f"error: {exc}", ok=False)
        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            return CommandResult(
                output=f"error: unknown command '{self.prefix}{name}'; "
                f"try '{self.prefix}help'",
                ok=False,
            )
        try:
            return handler(args)
        except UsageError as exc:
            return CommandResult(output=f"error: {exc}", ok=False)

    # -- individual commands -------------------------------------------------

    @staticmethod
    def _on_off(enabled: bool) -> str:
        return "on" if enabled else "off"

    def _cmd_help(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}help")
        return CommandResult(output=HELP_TEXT.format(prefix=self.prefix))

    def _cmd_status(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}status")
        return CommandResult(output=self._status_provider())

    def _cmd_output(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(output=f"output: {self.output.mode.value}")
        if len(args) != 1:
            raise UsageError(f"usage: {self.prefix}output shell|log|both")
        try:
            mode = OutputMode(args[0].lower())
        except ValueError as exc:
            raise UsageError(f"usage: {self.prefix}output shell|log|both") from exc
        self.output.set_mode(mode)
        return CommandResult(output=f"output: {mode.value}")

    def _cmd_logfile(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(output=f"logfile: {self.output.display_name()}")
        if len(args) != 1:
            raise UsageError(f"usage: {self.prefix}logfile <file>")
        self.output.set_logfile(args[0])
        return CommandResult(output=f"logfile: {self.output.display_name()}")

    def _cmd_framevalues(self, args: list[str]) -> CommandResult:
        usage = f"usage: {self.prefix}framevalues first|last|all"
        if not args:
            return CommandResult(output=f"frame values: {self.frames.mode.value}")
        if len(args) != 1:
            raise UsageError(usage)
        try:
            mode = FrameValueMode(args[0].lower())
        except ValueError as exc:
            raise UsageError(usage) from exc
        self.frames.set_mode(mode)
        return CommandResult(output=f"frame values: {mode.value}")

    def _cmd_frameagg(self, args: list[str]) -> CommandResult:
        usage = f"usage: {self.prefix}frameagg on|off"
        if not args:
            return CommandResult(
                output=f"frame aggregation: {self._on_off(self.aggregate.enabled)}"
            )
        if len(args) != 1:
            raise UsageError(usage)
        value = args[0].lower()
        if value not in ("on", "off"):
            raise UsageError(usage)
        self.aggregate.set_enabled(value == "on")
        return CommandResult(output=f"frame aggregation: {value}")

    def _cmd_quit(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}quit")
        return CommandResult(output="shutting down", quit=True)
