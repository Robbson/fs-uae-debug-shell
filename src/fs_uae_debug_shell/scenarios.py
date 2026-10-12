"""Named watchpoint scenarios loaded from ``config.yaml``.

A scenario groups memory watchpoints under stable, human-readable names
(aliases).  The wrapper assigns the debugger's watchpoint numbers itself, keeps
the alias for each number, and can add or remove a whole scenario with the
native ``w`` command.  The numbers are therefore an implementation detail and
the aliases can be used in the condensed output, the log file, the status line
and the shell commands.

The configuration is validated on load and a clearly located message is
reported for the first problem, so a broken file aborts startup instead of
silently producing wrong watchpoints.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import yaml

# An alias becomes a column/prompt label, so it must not contain whitespace
# (which would split a column), a comma (which would split a CSV cell) or a
# colon (the alias:value separator).
_NAME_RE = re.compile(r"^[^\s,:]+$")
_ADDRESS_RE = re.compile(r"^(\$|0[xX])?[0-9A-Fa-f]+$")
_FLAG_RE = re.compile(r"^[A-Za-z]+$")


class ConfigError(RuntimeError):
    """Raised when the scenario configuration is missing, malformed or invalid."""


def _fail(source: str, where: str, message: str) -> NoReturn:
    raise ConfigError(f"{source}: {where}: {message}")


@dataclass(frozen=True)
class ScenarioEntry:
    """One named watchpoint of a scenario, with defaults already applied."""

    name: str
    address: str
    length: int
    flags: tuple[str, ...]

    def command(self, watchpoint: int) -> str:
        """Return the native ``w`` command that adds or removes this watchpoint."""

        flags = " ".join(self.flags)
        return f"w {watchpoint} {self.address} {self.length} {flags}"


@dataclass(frozen=True)
class Scenario:
    """A named list of watchpoint entries."""

    name: str
    entries: tuple[ScenarioEntry, ...]


@dataclass(frozen=True)
class ScenarioCatalog:
    """The scenarios read from the configuration file, in file order."""

    scenarios: Mapping[str, Scenario] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ScenarioCatalog:
        return cls({})

    def __bool__(self) -> bool:
        return bool(self.scenarios)

    def names(self) -> list[str]:
        return list(self.scenarios)

    def get(self, name: str) -> Scenario | None:
        return self.scenarios.get(name)


class WatchpointRegistry:
    """Assign watchpoint numbers to active scenarios and remember their aliases."""

    def __init__(self, catalog: ScenarioCatalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else ScenarioCatalog.empty()
        self._next = 1
        self._aliases: dict[int, str] = {}
        self._active: dict[str, tuple[tuple[int, ScenarioEntry], ...]] = {}

    @property
    def catalog(self) -> ScenarioCatalog:
        return self._catalog

    @property
    def configured(self) -> bool:
        return bool(self._catalog)

    def names(self) -> list[str]:
        return self._catalog.names()

    def has(self, name: str) -> bool:
        return self._catalog.get(name) is not None

    def active_names(self) -> list[str]:
        """Return the active scenario names, in the order they were added."""

        return list(self._active)

    def alias(self, watchpoint: int) -> str | None:
        return self._aliases.get(watchpoint)

    def aliases(self) -> dict[int, str]:
        """Return a copy of the watchpoint-number to alias mapping."""

        return dict(self._aliases)

    def assignment(self, name: str) -> tuple[tuple[int, ScenarioEntry], ...]:
        """Return the ``(number, entry)`` pairs assigned to an active scenario."""

        return self._active.get(name, ())

    def add(self, name: str) -> list[str]:
        """Assign numbers to *name* and return the ``w`` commands to send."""

        scenario = self._catalog.get(name)
        if scenario is None:
            raise KeyError(name)
        commands: list[str] = []
        assigned: list[tuple[int, ScenarioEntry]] = []
        for entry in scenario.entries:
            number = self._next
            self._next += 1
            self._aliases[number] = entry.name
            assigned.append((number, entry))
            commands.append(entry.command(number))
        self._active[name] = tuple(assigned)
        return commands

    def remove(self, name: str) -> list[str]:
        """Free *name* and return the ``w`` commands that remove its watchpoints.

        A watchpoint is removed by its number alone (``w <num>``); the address,
        length and flags are only needed to add it.
        """

        assigned = self._active.pop(name)
        commands: list[str] = []
        for number, _entry in assigned:
            self._aliases.pop(number, None)
            commands.append(f"w {number}")
        return commands


# -- loading and validation -------------------------------------------------


def load_scenarios(path: Path) -> ScenarioCatalog:
    """Read and validate *path*; raise :class:`ConfigError` on any problem."""

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in '{path}': {exc}") from exc
    return parse_scenarios(data, source=str(path))


def parse_scenarios(data: Any, source: str = "config") -> ScenarioCatalog:
    """Validate an already-parsed configuration document."""

    if data is None:
        return ScenarioCatalog.empty()
    if not isinstance(data, Mapping):
        _fail(source, "config", "the document must be a mapping")
    unknown = sorted(set(data) - {"memwatch"})
    if unknown:
        _fail(source, "config", f"unknown key(s): {', '.join(unknown)}")
    memwatch = data.get("memwatch")
    if memwatch is None:
        return ScenarioCatalog.empty()
    if not isinstance(memwatch, Mapping):
        _fail(source, "memwatch", "must be a mapping")
    unknown = sorted(set(memwatch) - {"defaults", "scenarios"})
    if unknown:
        _fail(source, "memwatch", f"unknown key(s): {', '.join(unknown)}")

    default_length, default_flags = _parse_defaults(memwatch.get("defaults"), source)

    raw_scenarios = memwatch.get("scenarios")
    if raw_scenarios is None:
        return ScenarioCatalog.empty()
    if not isinstance(raw_scenarios, Mapping):
        _fail(source, "memwatch.scenarios", "must be a mapping of scenario names")

    scenarios: dict[str, Scenario] = {}
    for name, entries in raw_scenarios.items():
        where = f"memwatch.scenarios.{name}"
        if not isinstance(name, str) or not _NAME_RE.match(name):
            _fail(source, f"memwatch.scenarios.{name!r}", "invalid scenario name")
        if not isinstance(entries, list) or not entries:
            _fail(source, where, "must be a non-empty list of watchpoints")
        resolved: list[ScenarioEntry] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            item = _parse_entry(
                entry,
                source,
                f"{where}[{index}]",
                default_length,
                default_flags,
            )
            if item.name in seen:
                _fail(source, f"{where}[{index}]", f"duplicate watchpoint name '{item.name}'")
            seen.add(item.name)
            resolved.append(item)
        scenarios[name] = Scenario(name, tuple(resolved))
    return ScenarioCatalog(scenarios)


def _parse_defaults(
    defaults: Any, source: str
) -> tuple[int | None, tuple[str, ...] | None]:
    if defaults is None:
        return None, None
    if not isinstance(defaults, Mapping):
        _fail(source, "memwatch.defaults", "must be a mapping")
    unknown = sorted(set(defaults) - {"length", "flags"})
    if unknown:
        _fail(source, "memwatch.defaults", f"unknown key(s): {', '.join(unknown)}")
    length = None
    if "length" in defaults:
        length = _parse_length(defaults["length"], source, "memwatch.defaults")
    flags = None
    if "flags" in defaults:
        flags = _parse_flags(defaults["flags"], source, "memwatch.defaults")
    return length, flags


def _parse_entry(
    entry: Any,
    source: str,
    where: str,
    default_length: int | None,
    default_flags: tuple[str, ...] | None,
) -> ScenarioEntry:
    if not isinstance(entry, Mapping):
        _fail(source, where, "must be a mapping with 'name' and 'address'")
    unknown = sorted(set(entry) - {"name", "address", "length", "flags"})
    if unknown:
        _fail(source, where, f"unknown key(s): {', '.join(unknown)}")

    if "name" not in entry:
        _fail(source, where, "'name' is required")
    name = entry["name"]
    if not isinstance(name, str) or not _NAME_RE.match(name):
        _fail(
            source,
            where,
            "'name' must be a non-empty string without spaces, commas or colons",
        )

    if "address" not in entry:
        _fail(source, where, "'address' is required")
    address = _parse_address(entry["address"], source, where)

    if "length" in entry:
        length = _parse_length(entry["length"], source, where)
    elif default_length is not None:
        length = default_length
    else:
        _fail(source, where, "'length' is required (no default is set)")

    if "flags" in entry:
        flags = _parse_flags(entry["flags"], source, where)
    elif default_flags is not None:
        flags = default_flags
    else:
        _fail(source, where, "'flags' is required (no default is set)")

    return ScenarioEntry(name=name, address=address, length=length, flags=flags)


def _parse_address(value: Any, source: str, where: str) -> str:
    if isinstance(value, bool):
        _fail(source, where, "'address' must be a hexadecimal string")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not _ADDRESS_RE.match(value):
        _fail(source, where, "'address' must be a hexadecimal string (quote it, e.g. \"574\")")
    return value


def _parse_length(value: Any, source: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail(source, where, "'length' must be a positive integer")
    return value


def _parse_flags(value: Any, source: str, where: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _fail(source, where, "'flags' must be a list of flag letters, e.g. [W, C, L]")
    flags: list[str] = []
    for flag in value:
        if not isinstance(flag, str) or not _FLAG_RE.match(flag):
            _fail(source, where, "'flags' must contain only flag letters, e.g. [W, C, L]")
        flags.append(flag)
    if not flags:
        _fail(source, where, "'flags' must not be empty")
    return tuple(flags)
