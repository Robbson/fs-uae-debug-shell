from __future__ import annotations

import unittest
from pathlib import Path

from fs_uae_debug_wrapper.parser import (
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

    def test_watchpoint_hit_read_access(self) -> None:
        event = parse_line(
            "Memwatch 3: break at 00012345.B  R  0000000F PC=00001000 CPUWU (000)"
        )
        self.assertIsNotNone(event)
        assert event is not None and event.hit is not None
        self.assertEqual(event.hit.size, "B")
        self.assertEqual(event.hit.access, "R")
        self.assertEqual(event.hit.address, 0x12345)

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


if __name__ == "__main__":
    unittest.main()
