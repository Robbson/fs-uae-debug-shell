from __future__ import annotations

import unittest

from fs_uae_debug_shell.aggregate import (
    AggregatedFrame,
    FrameAggregator,
    format_frame_line,
)
from fs_uae_debug_shell.parser import DebuggerOutputParser

ENHANCED = (
    "00000969 Memwatch 02: 00000576.W  W  00000067 PC=0000C28C CPUDW (000)\n"
    "00000970 Memwatch 01: 00000574.W  W  0000002C PC=0000C28C CPUDW (000)\n"
    "00000970 Memwatch 02: 00000576.W  W  00000068 PC=0000C28C CPUDW (000)\n"
)

CLASSIC = (
    "Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)\n"
    "Memwatch 0: break at 00000574.W  W  0000005C PC=0000C28C CPUDW (000)\n"
)


def hit_pieces(text: str):
    pieces = DebuggerOutputParser().feed_pieces(text)
    return [piece for piece in pieces if piece.event and piece.event.hit is not None]


def run(text: str):
    aggregator = FrameAggregator()
    frames: list[AggregatedFrame] = []
    for piece in hit_pieces(text):
        frames.extend(aggregator.select(piece))
    frames.extend(aggregator.flush())
    return aggregator, frames


class FormatFrameLineTests(unittest.TestCase):
    def test_all_values_present(self) -> None:
        self.assertEqual(
            format_frame_line(969, {1: 0x29, 2: 0x67}, [1, 2]),
            "00000969 01:00000029 02:00000067",
        )

    def test_missing_value_keeps_padding(self) -> None:
        self.assertEqual(
            format_frame_line(969, {2: 0x67}, [1, 2]),
            "00000969 01:         02:00000067",
        )

    def test_watchpoint_ids_are_two_digit_padded(self) -> None:
        self.assertEqual(
            format_frame_line(1, {3: 0x1}, [3]),
            "00000001 03:00000001",
        )


class FrameAggregatorTests(unittest.TestCase):
    def test_default_enabled(self) -> None:
        self.assertTrue(FrameAggregator().enabled)

    def test_one_frame_per_row_and_missing_column(self) -> None:
        aggregator, frames = run(ENHANCED)
        self.assertEqual(aggregator.columns(), [1, 2])
        self.assertEqual(
            [(frame.frame, frame.values) for frame in frames],
            [(969, {2: 0x67}), (970, {1: 0x2C, 2: 0x68})],
        )

    def test_columns_can_be_seeded(self) -> None:
        aggregator = FrameAggregator()
        aggregator.add_columns([2, 1])
        self.assertEqual(aggregator.columns(), [1, 2])

    def test_repeated_watchpoint_keeps_last_value(self) -> None:
        text = (
            "00000100 Memwatch 01: 00000574.W  W  00000001 PC=0000C28C CPUDW (000)\n"
            "00000100 Memwatch 01: 00000574.W  W  00000002 PC=0000C28C CPUDW (000)\n"
        )
        _, frames = run(text)
        self.assertEqual([(frame.frame, frame.values) for frame in frames], [(100, {1: 2})])

    def test_classic_hits_are_not_buffered(self) -> None:
        aggregator = FrameAggregator()
        emitted: list[AggregatedFrame] = []
        for piece in hit_pieces(CLASSIC):
            emitted.extend(aggregator.select(piece))
        self.assertEqual(emitted, [])
        self.assertEqual(aggregator.flush(), [])

    def test_flush_without_buffer_returns_nothing(self) -> None:
        self.assertEqual(FrameAggregator().flush(), [])

    def test_disabling_drops_buffered_frame(self) -> None:
        aggregator = FrameAggregator()
        for piece in hit_pieces(ENHANCED):
            aggregator.select(piece)
        aggregator.set_enabled(False)
        self.assertFalse(aggregator.enabled)
        self.assertEqual(aggregator.flush(), [])

    def test_non_hit_pieces_are_ignored(self) -> None:
        aggregator = FrameAggregator()
        pieces = DebuggerOutputParser().feed_pieces("some text\n")
        self.assertEqual(aggregator.select(pieces[0]), [])


if __name__ == "__main__":
    unittest.main()
