"""Wrapper-specific commands, prefixed to keep them out of the FS-UAE namespace."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .eventlog import EventLogError
from .watchpoints import WatchpointManager


class UsageError(Exception):
    """Raised for malformed wrapper command arguments."""


@dataclass
class CommandResult:
    """Outcome of a wrapper command."""

    output: str = ""
    ok: bool = True
    quit: bool = False


HELP_TEXT = """\
wrapper commands (prefix '{prefix}'):
  {prefix}help                 show this help
  {prefix}status               show debugger state, watchpoints and log files
  {prefix}logwatch <id> <file> log watchpoint <id> hits to CSV <file>
  {prefix}logoff <id>          stop logging watchpoint <id>
  {prefix}auto on|off|toggle   enable/disable automatic resume after logging
  {prefix}quit                 stop the emulator and exit the wrapper
All other input is forwarded to the FS-UAE debugger unchanged."""


class CommandDispatcher:
    """Dispatch lines beginning with the wrapper prefix."""

    def __init__(
        self,
        *,
        prefix: str,
        manager: WatchpointManager,
        status_provider: Callable[[], str],
        auto_resume_get: Callable[[], bool],
        auto_resume_set: Callable[[bool], None],
        base_dir: Path,
    ) -> None:
        self.prefix = prefix
        self.manager = manager
        self._status_provider = status_provider
        self._auto_resume_get = auto_resume_get
        self._auto_resume_set = auto_resume_set
        self.base_dir = base_dir

    def handles(self, line: str) -> bool:
        return line.startswith(self.prefix)

    def dispatch(self, line: str) -> CommandResult:
        body = line[len(self.prefix) :].strip()
        if not body:
            return CommandResult(
                output=f"error: empty wrapper command; try '{self.prefix}help'",
                ok=False,
            )
        try:
            tokens = shlex.split(body)
        except ValueError as exc:
            return CommandResult(output=f"error: {exc}", ok=False)

        name = tokens[0].lower()
        args = tokens[1:]
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

    def _cmd_help(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}help")
        return CommandResult(output=HELP_TEXT.format(prefix=self.prefix))

    def _cmd_status(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}status")
        return CommandResult(output=self._status_provider())

    def _cmd_logwatch(self, args: list[str]) -> CommandResult:
        if len(args) != 2:
            raise UsageError(f"usage: {self.prefix}logwatch <watchpoint-id> <file>")
        watchpoint = _parse_watchpoint(args[0])
        try:
            config = self.manager.enable(
                watchpoint, args[1], base_dir=self.base_dir
            )
        except EventLogError as exc:
            return CommandResult(output=f"error: {exc}", ok=False)
        return CommandResult(
            output=f"logging watchpoint {watchpoint} to {config.path}"
        )

    def _cmd_logoff(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            raise UsageError(f"usage: {self.prefix}logoff <watchpoint-id>")
        watchpoint = _parse_watchpoint(args[0])
        if not self.manager.disable(watchpoint):
            return CommandResult(
                output=f"error: watchpoint {watchpoint} is not being logged",
                ok=False,
            )
        return CommandResult(output=f"stopped logging watchpoint {watchpoint}")

    def _cmd_auto(self, args: list[str]) -> CommandResult:
        if len(args) > 1:
            raise UsageError(f"usage: {self.prefix}auto [on|off|toggle]")
        if not args:
            enabled = not self._auto_resume_get()
        elif args[0].lower() in ("on", "yes", "true", "1"):
            enabled = True
        elif args[0].lower() in ("off", "no", "false", "0"):
            enabled = False
        elif args[0].lower() == "toggle":
            enabled = not self._auto_resume_get()
        else:
            raise UsageError(f"usage: {self.prefix}auto [on|off|toggle]")
        self._auto_resume_set(enabled)
        state = "enabled" if enabled else "disabled"
        return CommandResult(output=f"automatic resume {state}")

    def _cmd_quit(self, args: list[str]) -> CommandResult:
        if args:
            raise UsageError(f"usage: {self.prefix}quit")
        return CommandResult(output="shutting down", quit=True)


def _parse_watchpoint(token: str) -> int:
    text = token.strip().lstrip("$")
    try:
        value = int(text, 0)
    except ValueError as exc:
        raise UsageError(f"invalid watchpoint id '{token}'") from exc
    if value < 0:
        raise UsageError(f"watchpoint id must not be negative: '{token}'")
    return value
