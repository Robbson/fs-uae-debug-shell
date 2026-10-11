"""Watchpoint logging configuration, watch definitions and change filters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .eventlog import CsvEventWriter
from .parser import WatchpointHit


@dataclass
class Watch:
    """A watchpoint created with ``:wwcl`` and its change-filter state."""

    watchpoint: int
    name: str
    address: int
    length: int
    changed_only: bool = True
    last_value: int | None = None


@dataclass
class WatchpointLogging:
    """Association between a debugger watchpoint id and a CSV log file."""

    watchpoint: int
    path: Path
    writer: CsvEventWriter


def next_log_path(base_dir: Path, names: list[str]) -> Path:
    """Return the next free ``<name1>_<name2>_NNN.csv`` path in *base_dir*.

    The leading names are joined with ``_`` and a zero-padded counter is
    appended; the first counter (``000``) whose file does not exist is used.
    """

    base = "_".join(names)
    counter = 0
    while True:
        candidate = base_dir / f"{base}_{counter:03d}.csv"
        if not candidate.exists():
            return candidate
        counter += 1


class WatchpointManager:
    """Owns watch definitions, change filters and logging configurations."""

    def __init__(self) -> None:
        self._configs: dict[int, WatchpointLogging] = {}
        self._watches: dict[int, Watch] = {}

    # -- watch definitions ---------------------------------------------------

    def define_watch(
        self, watchpoint: int, name: str, address: int, length: int
    ) -> Watch:
        """Create or replace a change-filtered watch, resetting its value."""

        watch = Watch(
            watchpoint=watchpoint,
            name=name,
            address=address,
            length=length,
        )
        self._watches[watchpoint] = watch
        return watch

    def get_watch(self, watchpoint: int) -> Watch | None:
        return self._watches.get(watchpoint)

    def watches(self) -> list[Watch]:
        return [self._watches[key] for key in sorted(self._watches)]

    def is_duplicate(self, hit: WatchpointHit) -> bool:
        """Return whether *hit* repeats the last value of a filtered watch."""

        watch = self._watches.get(hit.watchpoint)
        if watch is None or not watch.changed_only:
            return False
        return watch.last_value is not None and watch.last_value == hit.value

    def observe(self, hit: WatchpointHit) -> None:
        """Remember the last value of a change-filtered watch."""

        watch = self._watches.get(hit.watchpoint)
        if watch is not None and watch.changed_only:
            watch.last_value = hit.value

    # -- logging configurations ----------------------------------------------

    def enable(
        self,
        watchpoint: int,
        path: str | Path,
        *,
        base_dir: Path | None = None,
    ) -> WatchpointLogging:
        """Enable logging for *watchpoint* into *path*.

        Relative paths are resolved against *base_dir* (default: current
        directory).  Raises :class:`EventLogError` if the file cannot be used.
        Re-enabling an existing watchpoint replaces and closes the old writer.
        """

        target = Path(path).expanduser()
        if not target.is_absolute() and base_dir is not None:
            target = base_dir / target
        writer = CsvEventWriter(target)
        existing = self._configs.get(watchpoint)
        if existing is not None:
            existing.writer.close()
        config = WatchpointLogging(watchpoint=watchpoint, path=target, writer=writer)
        self._configs[watchpoint] = config
        return config

    def disable(self, watchpoint: int) -> bool:
        """Disable logging for *watchpoint*; return whether it was configured."""

        config = self._configs.pop(watchpoint, None)
        if config is None:
            return False
        config.writer.close()
        return True

    def get(self, watchpoint: int) -> WatchpointLogging | None:
        return self._configs.get(watchpoint)

    def configs(self) -> list[WatchpointLogging]:
        return [self._configs[key] for key in sorted(self._configs)]

    def close(self) -> None:
        for config in self._configs.values():
            config.writer.close()
        self._configs.clear()
