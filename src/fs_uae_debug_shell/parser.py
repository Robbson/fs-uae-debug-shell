"""FS-UAE console-debugger output parsing.

The formats implemented here were confirmed against real FS-UAE sessions (see
``tests/fixtures``).  Both the original and the enhanced watchpoint-hit output
are recognised; nothing is inferred from WinUAE-only behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class EventType(Enum):
    """Kinds of structured events recognised in debugger output."""

    PROMPT = "prompt"
    DEBUGGER_ACTIVATED = "debugger_activated"
    DEBUGGER_SIGNAL_READY = "debugger_signal_ready"
    WATCHPOINTS_ENABLED = "watchpoints_enabled"
    WATCHPOINT_DEFINED = "watchpoint_defined"
    WATCHPOINT_HIT = "watchpoint_hit"


@dataclass(frozen=True)
class WatchpointHit:
    """A parsed ``Memwatch <n>: break at ...`` line.

    ``frame`` is the decimal frame counter of the enhanced output format, or
    ``None`` when the original format (which has no counter) was seen.
    """

    watchpoint: int
    address: int
    size: str
    access: str
    value: int
    pc: int
    trailer: str
    raw: str
    frame: int | None = None


@dataclass(frozen=True)
class WatchpointDefinition:
    """A parsed ``<n>: <start> - <end> (<len>)  <access>  <scope>`` line."""

    watchpoint: int
    start: int
    end: int
    length: int
    access: str
    scope: str
    raw: str


@dataclass(frozen=True)
class Event:
    """A single structured event produced by the parser."""

    type: EventType
    line: str = ""
    hit: WatchpointHit | None = None
    definition: WatchpointDefinition | None = None


@dataclass(frozen=True)
class Piece:
    """A unit of console output: its exact text plus any structured event.

    ``text`` is the raw text to display (including its line ending, when
    present) so that callers can forward output unchanged.  ``event`` is the
    structured event the line produced, if any.  ``in_dump`` marks a line that
    belongs to the CPU register dump the debugger prints when it stops (the
    block bracketed by ``-- stub -- activate_console`` and ``Next PC:``), so a
    caller can choose to hide it.  A prompt is emitted as a ``">"`` piece
    followed by a piece for the remainder of that line.
    """

    text: str
    event: Event | None = None
    in_dump: bool = False


# Confirmed hit formats from real sessions:
#   original (enhanced output off):
#     Memwatch 1: break at 00000574.L  W  000300AB  PC=00001234 CPUDW (000)
#   enhanced output on, with a leading decimal frame counter and no "break at":
#     00000025 Memwatch 01: 00000574.W  W  000000AB PC=00001234 CPUDW (000)
_HIT_RE = re.compile(
    r"^(?:(?P<frame>[0-9]{4,})\s+)?Memwatch\s+(?P<num>\d+):\s+"
    r"(?:break at\s+)?"
    r"(?P<addr>[0-9A-Fa-f]+)\.(?P<size>\S+)\s+"
    r"(?P<access>\S+)\s+(?P<value>[0-9A-Fa-f]+)\s+"
    r"PC=(?P<pc>[0-9A-Fa-f]+)\s*(?P<trailer>.*)$"
)

# Confirmed format from a real session:
#    0: 00000574 - 00000575 (2)  W  CPU
_DEF_RE = re.compile(
    r"^\s*(?P<num>\d+):\s*(?P<start>[0-9A-Fa-f]+)\s*-\s*(?P<end>[0-9A-Fa-f]+)\s*"
    r"\((?P<len>\d+)\)\s+(?P<access>\S+)\s+(?P<scope>\S+)\s*$"
)

_ACTIVATED_LINE = "WARNING: Activated debugger"
_WATCHPOINTS_ENABLED_LINE = "Memwatch breakpoints enabled"

# The forked FS-UAE build prints this marker once its SIGUSR1 handler is
# installed; the wrapper may only signal the process after this point, since an
# earlier SIGUSR1 uses the default action and kills FS-UAE.  Confirmed on the
# fs-uae-3 fork (see the upstream debugger skill); the surrounding prefix, if
# any, is not matched so the marker is recognised wherever it is printed.
_SIGNAL_READY_MARKER = "sending SIGUSR1 will activate the debugger"

# The CPU register dump the debugger prints when it stops is bracketed by these
# two lines: the stub marker the debugger prints on entering the console and the
# ``Next PC:`` line that closes the disassembly.  Confirmed on FS-UAE 3.2.35/3.3.0
# (see ``tests/fixtures``).  The user-run ``r`` command prints a similar dump
# without the stub marker, so it is deliberately not part of this block.
_DUMP_START_LINE = "-- stub -- activate_console"
_DUMP_END_PREFIX = "Next PC:"


def parse_line(line: str) -> Event | None:
    """Parse a single complete debugger output line into an event."""

    stripped = line.rstrip()
    if not stripped:
        return None
    if stripped == _ACTIVATED_LINE:
        return Event(EventType.DEBUGGER_ACTIVATED, line=stripped)
    if stripped == _WATCHPOINTS_ENABLED_LINE:
        return Event(EventType.WATCHPOINTS_ENABLED, line=stripped)
    if _SIGNAL_READY_MARKER in stripped:
        return Event(EventType.DEBUGGER_SIGNAL_READY, line=stripped)

    match = _HIT_RE.match(stripped)
    if match is not None:
        frame = match["frame"]
        hit = WatchpointHit(
            watchpoint=int(match["num"]),
            address=int(match["addr"], 16),
            size=match["size"].upper(),
            access=match["access"].upper(),
            value=int(match["value"], 16),
            pc=int(match["pc"], 16),
            trailer=match["trailer"],
            raw=stripped,
            frame=int(frame, 10) if frame is not None else None,
        )
        return Event(EventType.WATCHPOINT_HIT, line=stripped, hit=hit)

    match = _DEF_RE.match(stripped)
    if match is not None:
        definition = WatchpointDefinition(
            watchpoint=int(match["num"]),
            start=int(match["start"], 16),
            end=int(match["end"], 16),
            length=int(match["len"]),
            access=match["access"],
            scope=match["scope"],
            raw=stripped,
        )
        return Event(EventType.WATCHPOINT_DEFINED, line=stripped, definition=definition)

    return None


class DebuggerOutputParser:
    """Incremental parser for the FS-UAE debugger console stream.

    Output arrives in arbitrary chunks; :meth:`feed` accepts partial data and
    keeps the unfinished tail buffered.  The debugger prompt is a bare ``>``
    that is not newline terminated, so it is recognised as soon as it appears
    at the start of a line.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._in_dump = False

    def feed(self, text: str) -> list[Event]:
        """Consume *text* (may be partial) and return any complete events."""

        return [
            piece.event for piece in self.feed_pieces(text) if piece.event is not None
        ]

    def feed_pieces(self, text: str) -> list[Piece]:
        """Consume *text* and return raw output pieces in order.

        Each piece carries the exact text to display (including its line
        ending, where present) together with any structured event the line
        produced.  The same parse therefore drives both automation and what is
        shown to the user.

        The stream is walked with a cursor into a single buffer and only the
        unfinished tail is copied, so a large chunk costs one pass rather than
        a fresh slice per line.
        """

        self._buffer += text
        buffer = self._buffer
        pieces: list[Piece] = []
        start = 0
        end = len(buffer)
        while start < end:
            newline = buffer.find("\n", start)
            if newline == -1:
                if buffer[start] == ">":
                    self._in_dump = False
                    pieces.append(Piece(">", Event(EventType.PROMPT, line=">")))
                    start += 1
                    continue
                break
            raw = buffer[start : newline + 1]
            line = buffer[start:newline].rstrip("\r")
            start = newline + 1
            if line.startswith(">"):
                self._in_dump = False
                pieces.append(Piece(">", Event(EventType.PROMPT, line=">")))
                remainder = line[1:]
                if remainder.strip():
                    pieces.append(Piece(remainder + "\n", parse_line(remainder)))
                else:
                    pieces.append(Piece(raw[1:]))
                continue
            in_dump = self._advance_dump(line)
            pieces.append(Piece(raw, parse_line(line), in_dump=in_dump))
        self._buffer = buffer[start:]
        return pieces

    def _advance_dump(self, line: str) -> bool:
        """Track whether *line* is part of a CPU register dump block.

        Returns ``True`` while inside the block bracketed by
        ``-- stub -- activate_console`` and ``Next PC:``, and updates the
        parser's state so that a partial read does not lose the boundary.
        """

        stripped = line.strip()
        if self._in_dump:
            if stripped.startswith(_DUMP_END_PREFIX):
                self._in_dump = False
            return True
        if stripped == _DUMP_START_LINE:
            self._in_dump = True
            return True
        return False

    @property
    def pending(self) -> str:
        """Return the currently buffered, incomplete output."""

        return self._buffer
