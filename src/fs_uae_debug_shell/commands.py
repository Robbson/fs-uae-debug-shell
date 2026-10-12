"""Shell-specific commands, prefixed to keep them out of the FS-UAE namespace."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass

from .aggregate import FrameAggregator
from .dump import RegisterDump
from .frames import FrameValueMode, FrameValueSelector
from .output import OutputMode, OutputRouter
from .scenarios import WatchpointError, WatchpointRegistry, normalize_address


class UsageError(Exception):
    """Raised for malformed shell command arguments."""


@dataclass
class CommandResult:
    """Outcome of a shell command."""

    output: str = ""
    ok: bool = True
    quit: bool = False
    commands: tuple[str, ...] = ()


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
  {prefix}showdump on|off            show the CPU register dump the debugger
                                     prints when it stops (default: on)
  {prefix}<addr>[, <addr>[ <len>]]   add watchpoints by address using the
                                     config.yaml defaults (alias = address)
  {prefix}sci [add|rm <scenario>...] configure watchpoint scenarios from
                                     config.yaml ('*' selects every scenario;
                                     no argument lists the active ones)
  {prefix}quit                       stop the emulator and exit the shell
All other input is forwarded to the FS-UAE debugger unchanged."""

COMMANDS = (
    "help",
    "status",
    "output",
    "logfile",
    "framevalues",
    "frameagg",
    "showdump",
    "sci",
    "quit",
)
ARGUMENT_CHOICES: dict[str, tuple[str, ...]] = {
    "output": ("shell", "log", "both"),
    "framevalues": ("first", "last", "all"),
    "frameagg": ("on", "off"),
    "showdump": ("on", "off"),
    "sci": ("add", "rm"),
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
        scenarios: WatchpointRegistry,
        status_provider: Callable[[], str],
        dump: RegisterDump | None = None,
    ) -> None:
        self.prefix = prefix
        self.output = output
        self.frames = frames
        self.aggregate = aggregate
        self.scenarios = scenarios
        self.dump = dump if dump is not None else RegisterDump()
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
        if body[0].isdigit() or body[0] == "$":
            # No shell command starts with a number, so this is the address
            # shorthand: ``:<address>[, <address>[ <length>], ...]``.
            try:
                return self._cmd_addresses(body)
            except UsageError as exc:
                return CommandResult(output=f"error: {exc}", ok=False)
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

    def _cmd_showdump(self, args: list[str]) -> CommandResult:
        usage = f"usage: {self.prefix}showdump on|off"
        if not args:
            return CommandResult(
                output=f"register dump: {self._on_off(self.dump.enabled)}"
            )
        if len(args) != 1:
            raise UsageError(usage)
        value = args[0].lower()
        if value not in ("on", "off"):
            raise UsageError(usage)
        self.dump.set_enabled(value == "on")
        return CommandResult(output=f"register dump: {value}")

    def _cmd_addresses(self, body: str) -> CommandResult:
        """Add watchpoints straight from a comma-separated address list."""

        usage = (
            f"usage: {self.prefix}<address>[, <address>[ <length>], ...] "
            "(applies memwatch.defaults from config.yaml)"
        )
        entries = self._parse_addresses(body, usage)
        try:
            assigned = self.scenarios.add_addresses(entries)
        except WatchpointError as exc:
            return CommandResult(output=f"error: {exc}", ok=False)
        commands = tuple(entry.command(number) for number, entry in assigned)
        summary = ", ".join(f"{number}={entry.name}" for number, entry in assigned)
        return CommandResult(output=f"added watchpoints: {summary}", commands=commands)

    def _parse_addresses(
        self, body: str, usage: str
    ) -> list[tuple[str, int | None]]:
        entries: list[tuple[str, int | None]] = []
        for raw in body.split(","):
            token = raw.strip()
            if not token:
                raise UsageError(usage)
            parts = token.split()
            if len(parts) > 2:
                raise UsageError(usage)
            address = normalize_address(parts[0])
            if address is None:
                raise UsageError(
                    f"'{parts[0]}' is not a hexadecimal address"
                )
            length: int | None = None
            if len(parts) == 2:
                try:
                    length = int(parts[1])
                except ValueError:
                    raise UsageError(
                        f"'{parts[1]}' is not a length"
                    ) from None
                if length < 1:
                    raise UsageError("length must be a positive integer")
            entries.append((address, length))
        return entries

    def _cmd_sci(self, args: list[str]) -> CommandResult:
        usage = f"usage: {self.prefix}sci [add|rm <scenario> ...]"
        if not args:
            return CommandResult(output=self._sci_listing())
        sub = args[0].lower()
        if sub not in ("add", "rm") or len(args) < 2:
            raise UsageError(usage)
        if not self.scenarios.configured:
            raise UsageError(
                "no scenarios configured; create a config.yaml next to the shell "
                "or pass --config"
            )
        targets = self._sci_targets(args[1:], remove=sub == "rm")
        if sub == "add":
            return self._sci_add(targets)
        return self._sci_remove(targets)

    def _sci_targets(self, names: list[str], *, remove: bool) -> list[str]:
        if names == ["*"]:
            return self.scenarios.active_names() if remove else self.scenarios.names()
        if "*" in names:
            raise UsageError("'*' must be used on its own")
        return names

    def _sci_unknown(self, names: list[str]) -> None:
        unknown = [name for name in names if not self.scenarios.has(name)]
        if unknown:
            available = ", ".join(self.scenarios.names()) or "none"
            raise UsageError(
                f"unknown scenario(s): {', '.join(unknown)}; configured: {available}"
            )

    def _sci_add(self, names: list[str]) -> CommandResult:
        self._sci_unknown(names)
        commands: list[str] = []
        added: list[str] = []
        already: list[str] = []
        for name in names:
            if name in self.scenarios.active_names():
                already.append(name)
                continue
            commands.extend(self.scenarios.add(name))
            added.append(f"{name}: {self._describe_scenario(name)}")
        lines: list[str] = []
        if added:
            lines.append("added scenarios:\n  " + "\n  ".join(added))
        if already:
            lines.append("already active: " + ", ".join(already))
        if not lines:
            lines.append("no scenarios added")
        return CommandResult(output="\n".join(lines), commands=tuple(commands))

    def _sci_remove(self, names: list[str]) -> CommandResult:
        if not names:
            return CommandResult(output="no active scenarios")
        self._sci_unknown(names)
        active = self.scenarios.active_names()
        present = [name for name in names if name in active]
        absent = [name for name in names if name not in active]
        if not present:
            raise UsageError(
                "scenario(s) not active: " + ", ".join(absent or names)
            )
        commands: list[str] = []
        for name in present:
            commands.extend(self.scenarios.remove(name))
        lines = [f"removed scenarios: {', '.join(present)}"]
        if absent:
            lines.append("not active: " + ", ".join(absent))
        return CommandResult(output="\n".join(lines), commands=tuple(commands))

    def _sci_listing(self) -> str:
        if not self.scenarios.configured:
            return "no scenarios configured (create a config.yaml or pass --config)"
        names = self.scenarios.active_names()
        if not names:
            return "no active scenarios"
        lines = ["active scenarios:"]
        for name in names:
            lines.append(f"  {name}: {self._describe_scenario(name)}")
        return "\n".join(lines)

    def _describe_scenario(self, name: str) -> str:
        return ", ".join(
            f"{number}={entry.name}"
            for number, entry in self.scenarios.assignment(name)
        )

    def _cmd_quit(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}quit")
        return CommandResult(output="shutting down", quit=True)
