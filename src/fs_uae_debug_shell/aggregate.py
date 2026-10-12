"""Condense the watchpoint hits of a video frame into one row.

FS-UAE's enhanced watchpoint-hit output carries a leading video-frame counter and
can print many hits in a row while emulation keeps running.  Frame aggregation
keeps only the watchpoint ids and their values, one column per watchpoint, so a
frame reads as ``<frame> <wp>:<value> <wp>:<value> ...`` instead of one full hit
line each.  All the other hit fields (address, size, access, PC, trailer) are
dropped from this alternative view.

The classic hit output has no frame counter, so a frame cannot be identified and
the hits are passed through unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .parser import Piece

FRAME_WIDTH = 8
WATCHPOINT_WIDTH = 2
VALUE_WIDTH = 8


@dataclass(frozen=True)
class AggregatedFrame:
    """The selected value of each watchpoint in one video frame."""

    frame: int
    values: dict[int, int]


def format_frame_line(
    frame: int,
    values: dict[int, int],
    columns: Sequence[int],
    labels: Mapping[int, str] | None = None,
) -> str:
    """Return the terminal line for an aggregated frame.

    Every known *column* is printed, so a watchpoint that did not write in this
    frame keeps its padding as blanks instead of being dropped; a missing value
    must not look like a genuine one carried over from an earlier frame.  A
    column is named by its *labels* entry (a scenario alias) or, without one, by
    its zero-padded watchpoint id.
    """

    names = labels or {}
    parts = [f"{frame:0{FRAME_WIDTH}d}"]
    for watchpoint in columns:
        name = names.get(watchpoint, f"{watchpoint:0{WATCHPOINT_WIDTH}d}")
        if watchpoint in values:
            cell = f"{values[watchpoint]:0{VALUE_WIDTH}X}"
        else:
            cell = " " * VALUE_WIDTH
        parts.append(f"{name}:{cell}")
    return " ".join(parts)


class FrameAggregator:
    """Group selected watchpoint hits by frame and emit one row per frame.

    :meth:`select` is fed the same hit pieces that were kept per frame by
    :class:`~fs_uae_debug_shell.frames.FrameValueSelector` and returns a
    completed :class:`AggregatedFrame` whenever the frame number changes.
    :meth:`flush` emits the frame still buffered.  A repeated watchpoint in one
    frame keeps its last selected value, so ``:framevalues all`` still yields a
    single cell per watchpoint.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._frame: int | None = None
        self._values: dict[int, int] = {}
        self._columns: set[int] = set()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Turn aggregation on or off, dropping any buffered frame."""

        self._discard()
        self._enabled = enabled

    def add_columns(self, watchpoints: Iterable[int]) -> None:
        """Remember watchpoint ids so they are always printed as columns."""

        self._columns.update(watchpoints)

    def columns(self) -> list[int]:
        """Return the watchpoint ids that make up the table columns."""

        return sorted(self._columns)

    def select(self, piece: Piece) -> list[AggregatedFrame]:
        """Buffer a selected hit and return any frame completed by it."""

        event = piece.event
        if event is None or event.hit is None:
            return []
        hit = event.hit
        self._columns.add(hit.watchpoint)
        if hit.frame is None:
            # Classic output has no frame to aggregate into.
            return []
        completed: list[AggregatedFrame] = []
        if self._frame is not None and hit.frame != self._frame:
            completed.append(self._build())
        self._frame = hit.frame
        self._values[hit.watchpoint] = hit.value
        return completed

    def flush(self) -> list[AggregatedFrame]:
        """Return the buffered frame, if any."""

        if self._frame is None or not self._values:
            return []
        return [self._build()]

    def _build(self) -> AggregatedFrame:
        assert self._frame is not None
        aggregated = AggregatedFrame(self._frame, dict(self._values))
        self._discard()
        return aggregated

    def _discard(self) -> None:
        self._frame = None
        self._values.clear()
