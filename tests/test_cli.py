from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_shell import cli
from fs_uae_debug_shell.scenarios import ConfigError, ScenarioCatalog

FIXTURES = Path(__file__).parent / "fixtures"


class ResolveConfigPathTests(unittest.TestCase):
    def test_explicit_missing_path_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ConfigError):
            cli.resolve_config_path(str(Path(tmp) / "nope.yaml"), Path(tmp))

    def test_missing_default_is_inert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(cli.resolve_config_path(None, Path(tmp)))

    def test_default_is_used_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text("", encoding="utf-8")
            self.assertEqual(cli.resolve_config_path(None, Path(tmp)), config)


class ParseArgsTests(unittest.TestCase):
    def test_loads_explicit_config(self) -> None:
        config = cli.parse_args(["--config", str(FIXTURES / "config.yaml")])
        self.assertEqual(config.scenarios.names(), ["ball", "player1"])
        self.assertEqual(config.config_path, str(FIXTURES / "config.yaml"))

    def test_without_config_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = cli.parse_args([], cwd=Path(tmp))
        self.assertIsInstance(config.scenarios, ScenarioCatalog)
        self.assertEqual(config.scenarios.names(), [])
        self.assertIsNone(config.config_path)

    def test_default_config_is_loaded_from_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.yaml").write_text(
                (FIXTURES / "config.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            config = cli.parse_args([], cwd=Path(tmp))
        self.assertEqual(config.scenarios.names(), ["ball", "player1"])

    def test_invalid_config_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("memwatch:\n  scenarios:\n    ball: 3\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                cli.parse_args(["--config", str(path)])

    def test_fsuae_args_after_separator(self) -> None:
        config = cli.parse_args(["--", "--load_state=2", "game.fs-uae"])
        self.assertEqual(config.fsuae_args, ["--load_state=2", "game.fs-uae"])


class StartDebugTests(unittest.TestCase):
    def test_default_is_off(self) -> None:
        config = cli.parse_args(["--", "--load_state=2", "game.fs-uae"])
        self.assertFalse(config.start_debug)
        self.assertEqual(config.fsuae_args, ["--load_state=2", "game.fs-uae"])

    def test_adds_debugger_options(self) -> None:
        config = cli.parse_args(["--startdebug", "--", "--load_state=2", "game.fs-uae"])
        self.assertTrue(config.start_debug)
        self.assertEqual(
            config.fsuae_args,
            [
                "--console_debugger=1",
                "--debugger_signal=1",
                "--stdout",
                "--load_state=2",
                "game.fs-uae",
            ],
        )

    def test_does_not_duplicate_supplied_options(self) -> None:
        config = cli.parse_args(
            [
                "--startdebug",
                "--",
                "--console_debugger=1",
                "--debugger_signal=1",
                "--stdout",
                "game.fs-uae",
            ]
        )
        self.assertEqual(
            config.fsuae_args,
            [
                "--console_debugger=1",
                "--debugger_signal=1",
                "--stdout",
                "game.fs-uae",
            ],
        )

    def test_ensure_start_debug_args_detects_key_form(self) -> None:
        args = cli.ensure_start_debug_args(
            ["--console_debugger", "1", "--debugger_signal=1"]
        )
        self.assertEqual(args, ["--stdout", "--console_debugger", "1", "--debugger_signal=1"])


class MainTests(unittest.TestCase):
    def test_invalid_config_aborts_with_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("memwatch: 3\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = cli.main(["--config", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("memwatch", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
