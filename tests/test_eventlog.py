from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fs_uae_debug_shell.eventlog import HEADER, CsvEventWriter, EventLogError
from fs_uae_debug_shell.parser import WatchpointHit


def make_hit(value: int = 0x5B, frame: int | None = None) -> WatchpointHit:
    return WatchpointHit(
        watchpoint=0,
        address=0x574,
        size="W",
        access="W",
        value=value,
        pc=0xC28C,
        trailer="CPUDW (000)",
        raw="Memwatch 0: break at 00000574.W  W  0000005B PC=0000C28C CPUDW (000)",
        frame=frame,
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
            writer.append(make_hit(0x5B), timestamp=ts)
            writer.append(make_hit(0x5C), timestamp=ts)
            writer.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].split(","), HEADER)
            self.assertEqual(
                lines[1].split(","),
                [
                    "2026-10-10T12:00:00.000",
                    "",
                    "0",
                    "0x00000574",
                    "W",
                    "W",
                    "0x0000005B",
                    "0x0000C28C",
                ],
            )
            self.assertEqual(lines[2].split(",")[6], "0x0000005C")

    def test_frame_column_is_recorded_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            writer = CsvEventWriter(path)
            ts = datetime(2026, 10, 10, 12, 0, 0)
            writer.append(make_hit(0x5B, frame=25), timestamp=ts)
            writer.close()
            row = path.read_text(encoding="utf-8").splitlines()[1].split(",")
            self.assertEqual(row[1], "25")

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


class AggregatedCsvEventWriterTests(unittest.TestCase):
    def test_header_lists_watchpoint_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            CsvEventWriter(path, columns=[1, 2]).close()
            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines()[0],
                "timestamp,frame,wp1,wp2",
            )

    def test_append_frame_rows_with_empty_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            writer = CsvEventWriter(path, columns=[1, 2])
            ts = datetime(2026, 10, 12, 0, 31, 26, 549000)
            writer.append_frame(184, {1: 0x1D, 2: 0x60}, timestamp=ts)
            writer.append_frame(185, {2: 0x61}, timestamp=ts)
            writer.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                lines[1],
                "2026-10-12T00:31:26.549,184,0x0000001D,0x00000060",
            )
            self.assertEqual(
                lines[2],
                "2026-10-12T00:31:26.549,185,,0x00000061",
            )

    def test_append_frame_rejects_unknown_watchpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            writer = CsvEventWriter(path, columns=[1, 2])
            with self.assertRaises(EventLogError):
                writer.append_frame(184, {1: 0x1D, 9: 0x60})
            writer.close()

    def test_append_frame_on_classic_writer_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            writer = CsvEventWriter(path)
            with self.assertRaises(EventLogError):
                writer.append_frame(1, {0: 0x1})
            writer.close()

    def test_append_hit_on_aggregated_writer_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            writer = CsvEventWriter(path, columns=[0])
            with self.assertRaises(EventLogError):
                writer.append(make_hit())
            writer.close()

    def test_aggregated_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            classic = CsvEventWriter(Path(tmp) / "classic.csv")
            aggregated = CsvEventWriter(Path(tmp) / "aggregated.csv", columns=[1])
            self.assertFalse(classic.aggregated)
            self.assertTrue(aggregated.aggregated)
            classic.close()
            aggregated.close()


class LabeledCsvEventWriterTests(unittest.TestCase):
    def test_aggregated_header_uses_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            writer = CsvEventWriter(
                path, columns=[1, 2], labels={1: "ball.x", 2: "ball.y"}
            )
            writer.close()
            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines()[0],
                "timestamp,frame,ball.x,ball.y",
            )

    def test_aggregated_header_falls_back_to_wp_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            writer = CsvEventWriter(path, columns=[1, 2], labels={1: "ball.x"})
            writer.close()
            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines()[0],
                "timestamp,frame,ball.x,wp2",
            )

    def test_per_hit_wp_column_uses_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.csv"
            writer = CsvEventWriter(path, labels={0: "ball.x"})
            writer.append(make_hit(), timestamp=datetime(2026, 10, 10, 12, 0, 0))
            writer.close()
            row = path.read_text(encoding="utf-8").splitlines()[1].split(",")
            self.assertEqual(row[2], "ball.x")


if __name__ == "__main__":
    unittest.main()
