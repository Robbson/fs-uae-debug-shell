from __future__ import annotations

import unittest
from pathlib import Path

from fs_uae_debug_shell.parser import (
    DebuggerOutputParser,
    EventType,
    parse_line,
)

FIXTURES = Path(__file__).parent / "fixtures"


class ParseLineTests(unittest.TestCase):
    def test_watchpoint_hit(self) -> None:
        event = parse_line(
            "Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)"
        )
        self.assertIsNotNone(event)
        assert event is not None and event.hit is not None
        self.assertEqual(event.type, EventType.WATCHPOINT_HIT)
        hit = event.hit
        self.assertEqual(hit.watchpoint, 0)
        self.assertEqual(hit.address, 0x00000574)
        self.assertEqual(hit.size, "W")
        self.assertEqual(hit.access, "W")
        self.assertEqual(hit.value, 0x5B)
        self.assertEqual(hit.pc, 0x0000C28C)
        self.assertEqual(hit.trailer, "CPUDW (000)")
        self.assertIsNone(hit.frame)

    def test_watchpoint_hit_read_access(self) -> None:
        event = parse_line(
            "Memwatch 3: break at 00012345.B  R  0000000F PC=00001000 CPUWU (000)"
        )
        self.assertIsNotNone(event)
        assert event is not None and event.hit is not None
        self.assertEqual(event.hit.size, "B")
        self.assertEqual(event.hit.access, "R")
        self.assertEqual(event.hit.address, 0x12345)

    def test_watchpoint_hit_long_size_with_extra_spaces(self) -> None:
        event = parse_line(
            "Memwatch 1: break at 00000574.L  W  000300AB  PC=00001234 CPUDW (000)"
        )
        self.assertIsNotNone(event)
        assert event is not None and event.hit is not None
        self.assertEqual(event.hit.watchpoint, 1)
        self.assertEqual(event.hit.size, "L")
        self.assertEqual(event.hit.value, 0x300AB)
        self.assertEqual(event.hit.pc, 0x1234)

    def test_watchpoint_hit_enhanced_format(self) -> None:
        event = parse_line(
            "00000025 Memwatch 01: 00000574.W  W  000000AB PC=00001234 CPUDW (000)"
        )
        self.assertIsNotNone(event)
        assert event is not None and event.hit is not None
        self.assertEqual(event.type, EventType.WATCHPOINT_HIT)
        hit = event.hit
        self.assertEqual(hit.watchpoint, 1)
        self.assertEqual(hit.address, 0x574)
        self.assertEqual(hit.size, "W")
        self.assertEqual(hit.access, "W")
        self.assertEqual(hit.value, 0xAB)
        self.assertEqual(hit.pc, 0x1234)
        self.assertEqual(hit.trailer, "CPUDW (000)")
        self.assertEqual(hit.frame, 25)

    def test_both_hit_formats_agree(self) -> None:
        original = parse_line(
            "Memwatch 1: break at 00000574.W  W  000000AB PC=00001234 CPUDW (000)"
        )
        enhanced = parse_line(
            "00000025 Memwatch 01: 00000574.W  W  000000AB PC=00001234 CPUDW (000)"
        )
        assert original is not None and original.hit is not None
        assert enhanced is not None and enhanced.hit is not None
        self.assertEqual(original.hit.watchpoint, enhanced.hit.watchpoint)
        self.assertEqual(original.hit.address, enhanced.hit.address)
        self.assertEqual(original.hit.size, enhanced.hit.size)
        self.assertEqual(original.hit.access, enhanced.hit.access)
        self.assertEqual(original.hit.value, enhanced.hit.value)
        self.assertEqual(original.hit.pc, enhanced.hit.pc)
        self.assertEqual(original.hit.trailer, enhanced.hit.trailer)

    def test_activation_line(self) -> None:
        event = parse_line("WARNING: Activated debugger")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.type, EventType.DEBUGGER_ACTIVATED)

    def test_watchpoints_enabled_line(self) -> None:
        event = parse_line("Memwatch breakpoints enabled")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.type, EventType.WATCHPOINTS_ENABLED)

    def test_debugger_signal_ready_line(self) -> None:
        event = parse_line(
            "debugger_signal: sending SIGUSR1 will activate the debugger "
            "(requires console_debugger)"
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.type, EventType.DEBUGGER_SIGNAL_READY)

    def test_debugger_signal_ready_line_with_prefix(self) -> None:
        event = parse_line(
            "LOG: debugger_signal: sending SIGUSR1 will activate the debugger "
            "(requires console_debugger)"
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.type, EventType.DEBUGGER_SIGNAL_READY)

    def test_watchpoint_definition_line(self) -> None:
        event = parse_line(" 0: 00000574 - 00000575 (2)  W  CPU")
        self.assertIsNotNone(event)
        assert event is not None and event.definition is not None
        definition = event.definition
        self.assertEqual(definition.watchpoint, 0)
        self.assertEqual(definition.start, 0x574)
        self.assertEqual(definition.end, 0x575)
        self.assertEqual(definition.length, 2)
        self.assertEqual(definition.access, "W")
        self.assertEqual(definition.scope, "CPU")

    def test_unrelated_lines_are_ignored(self) -> None:
        for line in [
            "  D0 00000DB9   D1 00000028   D2 0000FFFF   D3 00000000",
            "USP  00C0BEF4 ISP  0007FFF8",
            "T=00 S=1 M=0 X=0 N=0 Z=1 V=0 C=0 IMASK=3 STP=0",
            "Next PC: 00008a6e",
            "0000C296 5279 0000 0590           ADD.W #$00000001,$00000590",
            "No breakpoints",
        ]:
            self.assertIsNone(parse_line(line), line)


class RegisterDumpTests(unittest.TestCase):
    """Pieces of the CPU register dump are flagged so they can be hidden."""

    BLOCK = (
        " -- stub -- activate_console \n"
        "  D0 00000F30   D1 00000028   D2 0000FFFF   D3 00000000 \n"
        "  A7 0007FFF8 \n"
        "USP  00C0BEF4 ISP  0007FFF8 \n"
        "T=00 S=1 M=0 X=0 N=0 Z=1 V=0 C=0 IMASK=3 STP=0\n"
        "Prefetch fffe (ILLEGAL) 48e7 (MVMLE) Chip latch 0000FFFE\n"
        "00008A6A 48e7 fffe                MOVEM.L D0-D7/A0-A6,-(A7)\n"
        "Next PC: 00008a6e\n"
    )

    def test_dump_block_is_marked(self) -> None:
        pieces = DebuggerOutputParser().feed_pieces(self.BLOCK)
        self.assertTrue(all(piece.in_dump for piece in pieces))
        self.assertEqual(pieces[0].text, " -- stub -- activate_console \n")
        self.assertEqual(pieces[-1].text, "Next PC: 00008a6e\n")
        self.assertTrue(all(piece.event is None for piece in pieces))

    def test_line_after_dump_is_not_marked(self) -> None:
        pieces = DebuggerOutputParser().feed_pieces(self.BLOCK + "No breakpoints\n")
        self.assertFalse(pieces[-1].in_dump)

    def test_other_stub_lines_are_not_marked(self) -> None:
        pieces = DebuggerOutputParser().feed_pieces(
            ' -- stub -- target_addtorecent name="x" t=0\n'
        )
        self.assertFalse(pieces[0].in_dump)

    def test_user_run_dump_is_not_marked(self) -> None:
        # The ``r`` command prints a similar dump without the stub marker, so it
        # stays transparent and is left untouched.
        pieces = DebuggerOutputParser().feed_pieces(
            ">r\n  D0 00000F30   D1 00000028\nNext PC: 00008a6e\n"
        )
        self.assertFalse(any(piece.in_dump for piece in pieces))

    def test_dump_boundary_survives_chunking(self) -> None:
        parser = DebuggerOutputParser()
        first = parser.feed_pieces(" -- stub -- activate_console\n  D0 00000F30\n")
        self.assertTrue(all(piece.in_dump for piece in first))
        second = parser.feed_pieces(
            "Next PC: 00008a6e\nMemwatch breakpoints enabled\n"
        )
        self.assertTrue(second[0].in_dump)
        self.assertFalse(second[1].in_dump)

    def test_prompt_ends_dump(self) -> None:
        parser = DebuggerOutputParser()
        parser.feed_pieces(" -- stub -- activate_console\n  D0 00000F30\n")
        pieces = parser.feed_pieces(">")
        self.assertFalse(pieces[-1].in_dump)
        assert pieces[-1].event is not None
        self.assertEqual(pieces[-1].event.type, EventType.PROMPT)
        pieces = parser.feed_pieces("No breakpoints\n")
        self.assertFalse(pieces[-1].in_dump)

    def test_activation_is_not_in_dump(self) -> None:
        pieces = DebuggerOutputParser().feed_pieces(
            "WARNING: Activated debugger\n" + self.BLOCK
        )
        self.assertFalse(pieces[0].in_dump)
        self.assertTrue(pieces[1].in_dump)



class ParserStreamTests(unittest.TestCase):
    def test_prompt_without_newline(self) -> None:
        parser = DebuggerOutputParser()
        events = parser.feed("Next PC: 00008a6e\r\n>")
        types = [event.type for event in events]
        self.assertIn(EventType.PROMPT, types)

    def test_partial_line_is_buffered(self) -> None:
        parser = DebuggerOutputParser()
        self.assertEqual(parser.feed("Memwatch 0: break at 00000574."), [])
        events = parser.feed("W  W  0000005B PC=0000C28C CPUDW (000)\r\n")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, EventType.WATCHPOINT_HIT)

    def test_prompt_then_command_echo(self) -> None:
        parser = DebuggerOutputParser()
        events = parser.feed(">g\r\n")
        self.assertEqual(events[0].type, EventType.PROMPT)

    def test_chunking_does_not_change_events(self) -> None:
        data = (FIXTURES / "watchpoint_session.txt").read_bytes().decode("latin-1")
        whole = DebuggerOutputParser()
        whole_events = whole.feed(data)

        chunked = DebuggerOutputParser()
        chunked_events = []
        for index in range(0, len(data), 7):
            chunked_events.extend(chunked.feed(data[index : index + 7]))

        self.assertEqual(len(whole_events), len(chunked_events))
        self.assertEqual(
            [event.type for event in whole_events],
            [event.type for event in chunked_events],
        )

    def test_session_fixture_contains_eight_hits(self) -> None:
        parser = DebuggerOutputParser()
        data = (FIXTURES / "watchpoint_session.txt").read_bytes().decode("latin-1")
        events = parser.feed(data)
        hits = [event.hit for event in events if event.type is EventType.WATCHPOINT_HIT]
        self.assertIsNotNone(hits)
        self.assertEqual(len(hits), 8)
        addresses = {hit.address for hit in hits if hit}
        self.assertEqual(addresses, {0x574})
        values = [hit.value for hit in hits if hit]
        self.assertEqual(values, [0x5B, 0x5B, 0x5C, 0x5D, 0x5D, 0x5E, 0x5E, 0x5E])
        for hit in hits:
            assert hit is not None
            self.assertEqual(hit.size, "W")
            self.assertEqual(hit.access, "W")
            self.assertEqual(hit.pc, 0xC28C)
        self.assertEqual(
            sum(event.type is EventType.DEBUGGER_ACTIVATED for event in events), 1
        )
        self.assertEqual(
            sum(event.type is EventType.WATCHPOINTS_ENABLED for event in events), 1
        )
        self.assertEqual(sum(event.type is EventType.PROMPT for event in events), 10)

    def test_single_hit_fixture(self) -> None:
        parser = DebuggerOutputParser()
        data = (FIXTURES / "watchpoint_session_1.txt").read_bytes().decode("latin-1")
        events = parser.feed(data)
        hits = [event.hit for event in events if event.type is EventType.WATCHPOINT_HIT]
        self.assertEqual(len(hits), 1)
        self.assertIsNotNone(hits[0])

    def test_feed_pieces_carry_raw_text_and_events(self) -> None:
        line = "Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)"
        pieces = DebuggerOutputParser().feed_pieces(line + "\r\n")
        self.assertEqual(len(pieces), 1)
        assert pieces[0].event is not None
        self.assertEqual(pieces[0].event.type, EventType.WATCHPOINT_HIT)
        self.assertEqual(pieces[0].text, line + "\r\n")

    def test_feed_pieces_enhanced_hit(self) -> None:
        line = "00000025 Memwatch 01: 00000574.W  W  000000AB PC=00001234 CPUDW (000)"
        pieces = DebuggerOutputParser().feed_pieces(line + "\r\n")
        self.assertEqual(len(pieces), 1)
        assert pieces[0].event is not None
        self.assertEqual(pieces[0].event.type, EventType.WATCHPOINT_HIT)
        self.assertEqual(pieces[0].text, line + "\r\n")

    def test_partial_enhanced_line_is_buffered(self) -> None:
        parser = DebuggerOutputParser()
        self.assertEqual(parser.feed("00000025 Memwatch 01: 00000574."), [])
        events = parser.feed("W  W  000000AB PC=00001234 CPUDW (000)\r\n")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, EventType.WATCHPOINT_HIT)

    def test_feed_pieces_prompt_without_newline_is_own_piece(self) -> None:
        pieces = DebuggerOutputParser().feed_pieces("Next PC: 00008a6e\n>")
        self.assertEqual(pieces[-1].text, ">")
        assert pieces[-1].event is not None
        self.assertEqual(pieces[-1].event.type, EventType.PROMPT)

    def test_feed_pieces_preserve_blank_lines(self) -> None:
        pieces = DebuggerOutputParser().feed_pieces("a\n\nb\n")
        self.assertEqual([piece.text for piece in pieces], ["a\n", "\n", "b\n"])
        self.assertTrue(all(piece.event is None for piece in pieces))

    def test_feed_events_match_feed_pieces(self) -> None:
        data = (FIXTURES / "watchpoint_session.txt").read_bytes().decode("latin-1")
        expected = DebuggerOutputParser().feed(data)
        pieces = DebuggerOutputParser().feed_pieces(data)
        actual = [piece.event for piece in pieces if piece.event is not None]
        self.assertEqual(
            [event.type for event in expected],
            [event.type for event in actual],
        )


if __name__ == "__main__":
    unittest.main()
