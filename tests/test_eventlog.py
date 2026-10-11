from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fs_uae_debug_wrapper.eventlog import HEADER, CsvEventWriter, EventLogError
from fs_uae_debug_wrapper.parser import WatchpointHit


def make_hit(value: int = 0x5B) -> WatchpointHit:
    return WatchpointHit(
        watchpoint=0,
        address=0x574,
        size="W",
        access="W",
        value=value,
        pc=0xC28C,
        trailer="CPUDW (000)",
        raw="Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)",
    )


class CsvEventWriterTests(unittest.TestCase):
    def test_new_file_gets_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            writer = CsvEventWriter(path)
            writer.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], ",".join(HEADER))

    def test_append_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            writer = CsvEventWriter(path)
            ts = datetime(2026, 10, 10, 12, 0, 0)
            writer.append(make_hit(0x5B), name="ball.x", timestamp=ts)
            writer.append(make_hit(0x5C), name="ball.x", timestamp=ts)
            writer.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].split(","), HEADER)
            self.assertEqual(
                lines[1].split(","),
                [
                    "2026-10-10T12:00:00.000",
                    "0",
                    "ball.x",
                    "0x00000574",
                    "W",
                    "W",
                    "0x0000005B",
                    "0x0000C28C",
                ],
            )
            self.assertEqual(lines[2].split(",")[6], "0x0000005C")

    def test_name_defaults_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            writer = CsvEventWriter(path)
            writer.append(make_hit())
            writer.close()
            row = path.read_text(encoding="utf-8").splitlines()[1].split(",")
            self.assertEqual(row[2], "")

    def test_reopen_does_not_duplicate_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            CsvEventWriter(path).close()
            writer = CsvEventWriter(path)
            writer.append(make_hit())
            writer.close()
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count(",".join(HEADER)), 1)

    def test_empty_existing_file_gets_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            path.touch()
            writer = CsvEventWriter(path)
            writer.close()
            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines()[0], ",".join(HEADER)
            )

    def test_invalid_path_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "adir"
            directory.mkdir()
            with self.assertRaises(EventLogError):
                CsvEventWriter(directory)

    def test_missing_parent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "score.csv"
            with self.assertRaises(EventLogError):
                CsvEventWriter(path)


if __name__ == "__main__":
    unittest.main()
