"""Watchpoint logging configuration management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .eventlog import CsvEventWriter


@dataclass
class WatchpointLogging:
    """Association between a debugger watchpoint id and a CSV log file."""

    watchpoint: int
    path: Path
    writer: CsvEventWriter


class WatchpointManager:
    """Owns the mapping from watchpoint ids to logging configurations."""

    def __init__(self) -> None:
        self._configs: dict[int, WatchpointLogging] = {}

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
