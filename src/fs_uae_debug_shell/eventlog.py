"""CSV logging of parsed watchpoint hits."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .parser import WatchpointHit

HEADER = ["timestamp", "wp", "address", "size", "access", "value", "pc"]


class EventLogError(RuntimeError):
    """Raised when a log file cannot be created, opened or written."""


def _hex(value: int, width: int = 8) -> str:
    return f"0x{value:0{width}X}"


class CsvEventWriter:
    """Append-only CSV writer for watchpoint hits.

    The file is opened in append mode.  A header row is written only when the
    file is newly created or empty.  Every record is flushed immediately so
    recent data survives an abrupt process termination.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            is_new = not self.path.exists() or self.path.stat().st_size == 0
        except OSError as exc:
            raise EventLogError(f"cannot access log file '{self.path}': {exc}") from exc
        try:
            self._file = self.path.open("a", encoding="utf-8", newline="")
        except OSError as exc:
            raise EventLogError(f"cannot open log file '{self.path}': {exc}") from exc
        self._writer = csv.writer(self._file)
        self._disabled = False
        if is_new:
            self._write_row(HEADER)

    def append(
        self,
        hit: WatchpointHit,
        timestamp: datetime | None = None,
    ) -> None:
        """Append one record for *hit*."""

        moment = timestamp if timestamp is not None else datetime.now()
        row = [
            moment.isoformat(timespec="milliseconds"),
            hit.watchpoint,
            _hex(hit.address),
            hit.size,
            hit.access,
            _hex(hit.value),
            _hex(hit.pc),
        ]
        self._write_row(row)

    def _write_row(self, row: list[object]) -> None:
        try:
            self._writer.writerow(row)
            self._file.flush()
        except OSError as exc:
            raise EventLogError(f"cannot write to log file '{self.path}': {exc}") from exc

    def close(self) -> None:
        if self._disabled:
            return
        self._disabled = True
        try:
            self._file.close()
        except OSError:
            pass
