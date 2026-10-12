"""Global routing of watchpoint hits to the screen and/or a CSV log file."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path

from .eventlog import CsvEventWriter
from .parser import WatchpointHit


class OutputMode(Enum):
    """Where watchpoint hits are sent."""

    SHELL = "shell"
    LOG = "log"
    BOTH = "both"


def default_logfile_name(now: datetime) -> str:
    """Return the default log file name for *now*.

    The name embeds a millisecond timestamp (``output_<timestamp>.csv``), so
    two sessions cannot collide.
    """

    stamp = now.strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
    return f"output_{stamp}.csv"


def _unique_path(base: Path) -> Path:
    """Return *base*, or ``<stem>_<n><suffix>`` if it already exists."""

    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    counter = 1
    while True:
        candidate = base.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


class OutputRouter:
    """Route all watchpoint hits to the screen, a CSV file, or both.

    A single CSV file collects hits from every watchpoint.  The file is created
    lazily: until the first hit is written, only the chosen name is kept in
    memory.  A user-supplied name that already exists is given an increasing
    numeric suffix so earlier logs are never overwritten.
    """

    def __init__(
        self,
        base_dir: Path,
        now: Callable[[], datetime] | None = None,
        columns: Callable[[], list[int]] | None = None,
        labels: Callable[[], dict[int, str]] | None = None,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._now = now if now is not None else datetime.now
        self._columns = columns if columns is not None else list
        self._labels = labels if labels is not None else dict
        self._mode = OutputMode.SHELL
        self._user_name: str | None = None
        self._default_name: str | None = None
        self._writer: CsvEventWriter | None = None
        self._path: Path | None = None
        self._counts: dict[int, int] = {}

    # -- configuration -------------------------------------------------------

    @property
    def mode(self) -> OutputMode:
        return self._mode

    def set_mode(self, mode: OutputMode) -> None:
        self._mode = mode

    def set_logfile(self, name: str) -> None:
        """Set a new log file name, discarding any open file and its counts."""

        self._user_name = name
        self._close_writer()
        self._counts.clear()

    @property
    def display_enabled(self) -> bool:
        """Whether hits are shown on the screen."""

        return self._mode in (OutputMode.SHELL, OutputMode.BOTH)

    @property
    def log_enabled(self) -> bool:
        """Whether hits are written to the CSV file."""

        return self._mode in (OutputMode.LOG, OutputMode.BOTH)

    @property
    def show_counters(self) -> bool:
        """Whether the per-watchpoint counter line should be displayed."""

        return self._mode is OutputMode.LOG

    @property
    def created(self) -> bool:
        """Whether the log file has been created on disk yet."""

        return self._writer is not None

    def display_name(self) -> str:
        """Return the effective log file path (without creating it)."""

        if self._path is not None:
            return str(self._path)
        return str(self._base_path())

    # -- recording -----------------------------------------------------------

    def record(self, hit: WatchpointHit) -> None:
        """Append *hit* to the log file when logging is enabled.

        Raises :class:`EventLogError` if the file cannot be opened or written.
        """

        if not self.log_enabled:
            return
        writer = self._ensure_writer(aggregated=False)
        writer.append(hit, timestamp=self._now())
        self._counts[hit.watchpoint] = self._counts.get(hit.watchpoint, 0) + 1

    def record_frame(self, frame: int, values: dict[int, int]) -> None:
        """Append an aggregated *frame* to the log file when logging is enabled.

        One row is written per frame, with a column per watchpoint.  Raises
        :class:`EventLogError` if the file cannot be opened or written.
        """

        if not self.log_enabled:
            return
        writer = self._ensure_writer(aggregated=True)
        writer.append_frame(frame, values, timestamp=self._now())
        for watchpoint in values:
            self._counts[watchpoint] = self._counts.get(watchpoint, 0) + 1

    def counts(self) -> dict[int, int]:
        return dict(self._counts)

    @property
    def total(self) -> int:
        return sum(self._counts.values())

    def close(self) -> None:
        self._close_writer()

    # -- helpers -------------------------------------------------------------

    def _base_path(self) -> Path:
        if self._user_name is not None:
            candidate = Path(self._user_name).expanduser()
            if not candidate.is_absolute():
                candidate = self._base_dir / candidate
            return candidate
        if self._default_name is None:
            self._default_name = default_logfile_name(self._now())
        return self._base_dir / self._default_name

    def _ensure_writer(self, aggregated: bool) -> CsvEventWriter:
        if self._writer is not None:
            if self._writer.aggregated == aggregated:
                return self._writer
            # The record shape changed (for example :frameagg was toggled while
            # logging): start a fresh file with the matching schema so rows and
            # header stay consistent.
            self._close_writer()
            self._counts.clear()
        path = _unique_path(self._base_path())
        columns = self._columns() if aggregated else None
        writer = CsvEventWriter(path, columns=columns, labels=self._labels())
        self._writer = writer
        self._path = path
        return writer

    def _close_writer(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._path = None
