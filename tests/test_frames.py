from __future__ import annotations

import unittest
from pathlib import Path

from fs_uae_debug_shell.frames import FrameValueMode, FrameValueSelector
from fs_uae_debug_shell.parser import DebuggerOutputParser

FIXTURE = Path(__file__).parent / "fixtures" / "enhanced_frames.txt"

# (watchpoint, value, frame) triples in the order the fixture lists them.
FIXTURE_HITS = [
    (1, 0x03, 164),
    (2, 0x93, 164),
    (2, 0x94, 165),
    (2, 0x95, 165),
    (2, 0x8E, 165),
    (2, 0x8D, 166),
    (2, 0x8C, 166),
    (2, 0x8B, 166),
    (2, 0x8A, 166),
    (2, 0x89, 166),
    (2, 0x88, 166),
]

CLASSIC = "\n".join(
    f"Memwatch 0: break at 00000574.W  W  {value:08X} PC=0000C28C CPUDW (000)"
    for value in (0x5B, 0x5C, 0x5D)
) + "\n"


def hit_pieces(text: str):
    pieces = DebuggerOutputParser().feed_pieces(text)
    return [piece for piece in pieces if piece.event and piece.event.hit is not None]


def describe(pieces) -> list[tuple[int, int, int | None]]:
    return [
        (piece.event.hit.watchpoint, piece.event.hit.value, piece.event.hit.frame)
        for piece in pieces
        if piece.event is not None and piece.event.hit is not None
    ]


class FrameValueSelectorTests(unittest.TestCase):
    def run_selector(self, mode: FrameValueMode, text: str, flush: bool = True):
        selector = FrameValueSelector(mode)
        emitted = []
        for piece in hit_pieces(text):
            emitted.extend(selector.select(piece))
        if flush:
            emitted.extend(selector.flush())
        return describe(emitted)

    def test_default_mode_is_first(self) -> None:
        self.assertIs(FrameValueSelector().mode, FrameValueMode.FIRST)

    def test_all_keeps_every_hit(self) -> None:
        self.assertEqual(
            self.run_selector(FrameValueMode.ALL, FIXTURE.read_text()), FIXTURE_HITS
        )

    def test_first_keeps_first_per_watchpoint_and_frame(self) -> None:
        self.assertEqual(
            self.run_selector(FrameValueMode.FIRST, FIXTURE.read_text()),
            [(1, 0x03, 164), (2, 0x93, 164), (2, 0x94, 165), (2, 0x8D, 166)],
        )

    def test_last_keeps_last_per_watchpoint_and_frame(self) -> None:
        self.assertEqual(
            self.run_selector(FrameValueMode.LAST, FIXTURE.read_text()),
            [(1, 0x03, 164), (2, 0x93, 164), (2, 0x8E, 165), (2, 0x88, 166)],
        )

    def test_last_emits_on_frame_boundary(self) -> None:
        selector = FrameValueSelector(FrameValueMode.LAST)
        emitted = []
        for piece in hit_pieces(FIXTURE.read_text()):
            emitted.extend(selector.select(piece))
        # The final frame is still buffered until flushed explicitly.
        self.assertEqual(
            describe(emitted), [(1, 0x03, 164), (2, 0x93, 164), (2, 0x8E, 165)]
        )
        self.assertEqual(describe(selector.flush()), [(2, 0x88, 166)])

    def test_classic_hits_ignore_mode(self) -> None:
        for mode in FrameValueMode:
            self.assertEqual(
                len(self.run_selector(mode, CLASSIC)), 3, mode
            )

    def test_set_mode_drops_buffered_frame(self) -> None:
        selector = FrameValueSelector(FrameValueMode.LAST)
        for piece in hit_pieces(FIXTURE.read_text())[:2]:
            selector.select(piece)
        selector.set_mode(FrameValueMode.FIRST)
        self.assertEqual(selector.flush(), [])

    def test_select_ignores_non_hit_pieces(self) -> None:
        selector = FrameValueSelector(FrameValueMode.FIRST)
        pieces = DebuggerOutputParser().feed_pieces("some text\n")
        self.assertEqual(selector.select(pieces[0]), pieces)


if __name__ == "__main__":
    unittest.main()
