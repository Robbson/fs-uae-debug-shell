"""CSV logging of parsed watchpoint hits."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from .parser import WatchpointHit

HEADER = ["timestamp", "frame", "wp", "address", "size", "access", "value", "pc"]


class EventLogError(RuntimeError):
    """Raised when a log file cannot be created, opened or written."""


def _hex(value: int, width: int = 8) -> str:
    return f"0x{value:0{width}X}"


def aggregated_header(
    columns: Sequence[int], labels: Mapping[int, str] | None = None
) -> list[str]:
    """Return the wide header used by frame aggregation, one column per watchpoint.

    A column is named by its *labels* entry (a scenario alias) or, without one,
    by ``wp<id>``.
    """

    names = labels or {}
    return [
        "timestamp",
        "frame",
        *(names.get(watchpoint, f"wp{watchpoint}") for watchpoint in columns),
    ]


class CsvEventWriter:
    """Append-only CSV writer for watchpoint hits.

    The file is opened in append mode.  A header row is written only when the
    file is newly created or empty.  Every record is flushed immediately so
    recent data survives an abrupt process termination.

    With *columns* the writer uses the wide frame-aggregation schema
    (``timestamp,frame,wp1,wp2,...``) and accepts whole frames via
    :meth:`append_frame`; without it the writer uses the per-hit schema and
    accepts single hits via :meth:`append`.  *labels* names the watchpoint
    columns (and the per-hit ``wp`` value) using scenario aliases when available.
    """

    def __init__(
        self,
        path: Path,
        columns: Sequence[int] | None = None,
        labels: Mapping[int, str] | None = None,
    ) -> None:
        self.path = Path(path)
        self._columns = None if columns is None else tuple(columns)
        self._labels = dict(labels or {})
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
            self._write_row(self._header())

    @property
    def aggregated(self) -> bool:
        """Whether this file uses the wide frame-aggregation schema."""

        return self._columns is not None

    def _header(self) -> list[str]:
        if self._columns is None:
            return HEADER
        return aggregated_header(self._columns, self._labels)

    def append(
        self,
        hit: WatchpointHit,
        timestamp: datetime | None = None,
    ) -> None:
        """Append one record for *hit*."""

        if self._columns is not None:
            raise EventLogError(
                f"cannot append a single hit to the aggregated log '{self.path}'"
            )
        moment = timestamp if timestamp is not None else datetime.now()
        row = [
            moment.isoformat(timespec="milliseconds"),
            hit.frame if hit.frame is not None else "",
            self._labels.get(hit.watchpoint, hit.watchpoint),
            _hex(hit.address),
            hit.size,
            hit.access,
            _hex(hit.value),
            _hex(hit.pc),
        ]
        self._write_row(row)

    def append_frame(
        self,
        frame: int,
        values: dict[int, int],
        timestamp: datetime | None = None,
    ) -> None:
        """Append one record for an aggregated *frame*.

        Each schema column holds the frame's value for that watchpoint, or an
        empty cell when the watchpoint did not write in the frame.  A
        watchpoint outside the schema is an error rather than silently dropped:
        the header was fixed when the file was created.
        """

        if self._columns is None:
            raise EventLogError(
                f"cannot append an aggregated frame to the classic log '{self.path}'"
            )
        unknown = sorted(set(values) - set(self._columns))
        if unknown:
            raise EventLogError(
                f"watchpoint(s) {', '.join(str(w) for w in unknown)} appeared after "
                f"the aggregation header of '{self.path}' was written; start a new "
                f"log file"
            )
        moment = timestamp if timestamp is not None else datetime.now()
        row: list[object] = [moment.isoformat(timespec="milliseconds"), frame]
        for watchpoint in self._columns:
            value = values.get(watchpoint)
            row.append("" if value is None else _hex(value))
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
