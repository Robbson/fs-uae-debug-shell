"""FS-UAE console-debugger output parsing.

The formats implemented here were confirmed against real FS-UAE 3.2.35
sessions (see ``tests/fixtures``).  Nothing is inferred from WinUAE-only
behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class EventType(Enum):
    """Kinds of structured events recognised in debugger output."""

    PROMPT = "prompt"
    DEBUGGER_ACTIVATED = "debugger_activated"
    WATCHPOINTS_ENABLED = "watchpoints_enabled"
    WATCHPOINT_DEFINED = "watchpoint_defined"
    WATCHPOINT_HIT = "watchpoint_hit"


@dataclass(frozen=True)
class WatchpointHit:
    """A parsed ``Memwatch <n>: break at ...`` line."""

    watchpoint: int
    address: int
    size: str
    access: str
    value: int
    pc: int
    trailer: str
    raw: str


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
    structured event the line produced, if any.  A prompt is emitted as a
    ``">"`` piece followed by a piece for the remainder of that line.
    """

    text: str
    event: Event | None = None


# Confirmed format from a real session:
#   Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)
_HIT_RE = re.compile(
    r"^Memwatch\s+(?P<num>\d+):\s+break at\s+"
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


def parse_line(line: str) -> Event | None:
    """Parse a single complete debugger output line into an event."""

    stripped = line.rstrip()
    if not stripped:
        return None
    if stripped == _ACTIVATED_LINE:
        return Event(EventType.DEBUGGER_ACTIVATED, line=stripped)
    if stripped == _WATCHPOINTS_ENABLED_LINE:
        return Event(EventType.WATCHPOINTS_ENABLED, line=stripped)

    match = _HIT_RE.match(stripped)
    if match is not None:
        hit = WatchpointHit(
            watchpoint=int(match["num"]),
            address=int(match["addr"], 16),
            size=match["size"].upper(),
            access=match["access"].upper(),
            value=int(match["value"], 16),
            pc=int(match["pc"], 16),
            trailer=match["trailer"],
            raw=stripped,
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
        """

        self._buffer += text
        pieces: list[Piece] = []
        while self._buffer:
            newline = self._buffer.find("\n")
            if newline == -1:
                if self._buffer.startswith(">"):
                    pieces.append(Piece(">", Event(EventType.PROMPT, line=">")))
                    self._buffer = self._buffer[1:]
                    continue
                break
            raw = self._buffer[: newline + 1]
            line = self._buffer[:newline].rstrip("\r")
            self._buffer = self._buffer[newline + 1 :]
            if line.startswith(">"):
                pieces.append(Piece(">", Event(EventType.PROMPT, line=">")))
                remainder = line[1:]
                if remainder.strip():
                    pieces.append(Piece(remainder + "\n", parse_line(remainder)))
                else:
                    pieces.append(Piece(raw[1:]))
                continue
            pieces.append(Piece(raw, parse_line(line)))
        return pieces

    @property
    def pending(self) -> str:
        """Return the currently buffered, incomplete output."""

        return self._buffer
