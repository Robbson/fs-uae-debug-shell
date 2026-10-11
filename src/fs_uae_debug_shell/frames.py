"""Selection of which watchpoint hits of a video frame to emit.

The enhanced FS-UAE watchpoint-hit output prefixes each hit with a video-frame
counter.  A single frame can contain several writes to the same watchpoint
because the game loop runs more often than frames are rendered, and only one of
those values (usually the first or the last) is actually shown on screen.  The
user chooses which value per frame and per watchpoint is displayed and logged.

The classic hit output has no frame counter, so the choice does not apply there
and every hit is emitted.
"""

from __future__ import annotations

from enum import Enum

from .parser import Piece


class FrameValueMode(Enum):
    """Which hits of a frame are kept, per watchpoint."""

    FIRST = "first"
    LAST = "last"
    ALL = "all"


class FrameValueSelector:
    """Select the watchpoint-hit pieces to emit, grouped by frame.

    ``select`` is fed every watchpoint-hit ``Piece`` in order and returns the
    pieces to emit now.  ``all`` (and any hit without a frame counter) is
    emitted immediately; ``first`` emits the first hit of each watchpoint in a
    frame and drops the rest; ``last`` buffers a frame and emits one hit per
    watchpoint when the frame changes.  ``flush`` emits the buffered frame.
    """

    def __init__(self, mode: FrameValueMode = FrameValueMode.FIRST) -> None:
        self._mode = mode
        self._frame: int | None = None
        self._seen: set[int] = set()
        self._pending: dict[int, Piece] = {}
        self._order: list[int] = []

    @property
    def mode(self) -> FrameValueMode:
        return self._mode

    def set_mode(self, mode: FrameValueMode) -> None:
        """Change the mode, dropping any buffered frame.

        The mode is changed from the debugger prompt, where a frame stream has
        already ended and been flushed.  Dropping a leftover buffer keeps the
        new mode from replaying values it did not select.
        """

        self._discard()
        self._mode = mode

    def select(self, piece: Piece) -> list[Piece]:
        """Return the pieces to emit now for watchpoint-hit *piece*."""

        event = piece.event
        if event is None or event.hit is None:
            return [piece]
        hit = event.hit
        frame = hit.frame
        if frame is None or self._mode is FrameValueMode.ALL:
            # Classic output, or "all": nothing to group or drop.
            return self._flush() + [piece]
        if self._mode is FrameValueMode.FIRST:
            if frame != self._frame:
                self._frame = frame
                self._seen.clear()
            if hit.watchpoint in self._seen:
                return []
            self._seen.add(hit.watchpoint)
            return [piece]
        # FrameValueMode.LAST
        emitted = self._flush() if frame != self._frame else []
        self._frame = frame
        if hit.watchpoint not in self._pending:
            self._order.append(hit.watchpoint)
        self._pending[hit.watchpoint] = piece
        return emitted

    def flush(self) -> list[Piece]:
        """Return the buffered frame's hits, if any."""

        return self._flush()

    def _flush(self) -> list[Piece]:
        if not self._pending:
            return []
        pieces = [self._pending[watchpoint] for watchpoint in self._order]
        self._discard()
        return pieces

    def _discard(self) -> None:
        self._frame = None
        self._seen.clear()
        self._pending.clear()
        self._order.clear()
