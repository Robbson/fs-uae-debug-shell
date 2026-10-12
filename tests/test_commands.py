from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_shell.aggregate import FrameAggregator
from fs_uae_debug_shell.commands import CommandDispatcher
from fs_uae_debug_shell.frames import FrameValueSelector
from fs_uae_debug_shell.output import OutputMode, OutputRouter
from fs_uae_debug_shell.scenarios import WatchpointRegistry, load_scenarios

FIXTURES = Path(__file__).parent / "fixtures"


def make_dispatcher(
    case: unittest.TestCase,
    tmp: str,
    scenarios: WatchpointRegistry | None = None,
) -> tuple[CommandDispatcher, OutputRouter]:
    router = OutputRouter(Path(tmp))
    case.addCleanup(router.close)

    def status() -> str:
        return "state: stopped"

    dispatcher = CommandDispatcher(
        prefix=":",
        output=router,
        frames=FrameValueSelector(),
        aggregate=FrameAggregator(),
        scenarios=scenarios if scenarios is not None else WatchpointRegistry(),
        status_provider=status,
    )
    return dispatcher, router


def ball_registry() -> WatchpointRegistry:
    return WatchpointRegistry(load_scenarios(FIXTURES / "config.yaml"))


class CommandDispatcherTests(unittest.TestCase):
    def test_handles_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            self.assertTrue(dispatcher.handles(":help"))
            self.assertFalse(dispatcher.handles("r"))
            self.assertFalse(dispatcher.handles("g"))

    def test_help(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":help")
            self.assertTrue(result.ok)
            self.assertIn("shell commands", result.output)
            self.assertIn("output", result.output)
            self.assertIn("logfile", result.output)
            self.assertIn("framevalues", result.output)
            self.assertIn("frameagg", result.output)
            self.assertIn("showdump", result.output)

    def test_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":status")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "state: stopped")

    def test_unknown_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":bogus")
            self.assertFalse(result.ok)
            self.assertIn("unknown command", result.output)

    def test_empty_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":")
            self.assertFalse(result.ok)

    def test_output_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "output: shell")

    def test_output_sets_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            for value in ("log", "both", "shell"):
                result = dispatcher.dispatch(f":output {value}")
                self.assertTrue(result.ok, result.output)
                self.assertIs(router.mode, OutputMode(value))

    def test_output_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output BOTH")
            self.assertTrue(result.ok)
            self.assertIs(router.mode, OutputMode.BOTH)

    def test_output_invalid_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output screen")
            self.assertFalse(result.ok)

    def test_output_too_many_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":output log both")
            self.assertFalse(result.ok)

    def test_logfile_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logfile")
            self.assertTrue(result.ok)
            self.assertIn("output_", result.output)
            self.assertIn(".csv", result.output)

    def test_logfile_sets_name_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logfile game.csv")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(Path(tmp, "game.csv").exists(), False)
            self.assertFalse(router.created)

    def test_logfile_quoted_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, router = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(':logfile "my log.csv"')
            self.assertTrue(result.ok, result.output)
            self.assertTrue(router.display_name().endswith("my log.csv"))

    def test_logfile_wrong_arity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logfile a.csv b.csv")
            self.assertFalse(result.ok)

    def test_framevalues_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "frame values: first")

    def test_framevalues_sets_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            for value in ("last", "all", "first"):
                result = dispatcher.dispatch(f":framevalues {value}")
                self.assertTrue(result.ok, result.output)
                self.assertEqual(dispatcher.frames.mode.value, value)

    def test_framevalues_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues ALL")
            self.assertTrue(result.ok)
            self.assertEqual(dispatcher.frames.mode.value, "all")

    def test_framevalues_invalid_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues sometimes")
            self.assertFalse(result.ok)

    def test_framevalues_too_many_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":framevalues first last")
            self.assertFalse(result.ok)

    def test_frameagg_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":frameagg")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "frame aggregation: on")

    def test_frameagg_sets_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            for value in ("off", "on", "off"):
                result = dispatcher.dispatch(f":frameagg {value}")
                self.assertTrue(result.ok, result.output)
                self.assertEqual(result.output, f"frame aggregation: {value}")
                self.assertEqual(dispatcher.aggregate.enabled, value == "on")

    def test_frameagg_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":frameagg OFF")
            self.assertTrue(result.ok)
            self.assertFalse(dispatcher.aggregate.enabled)

    def test_frameagg_invalid_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":frameagg maybe")
            self.assertFalse(result.ok)

    def test_frameagg_too_many_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":frameagg on off")
            self.assertFalse(result.ok)

    def test_showdump_reports_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":showdump")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "register dump: on")

    def test_showdump_sets_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            for value in ("off", "on", "off"):
                result = dispatcher.dispatch(f":showdump {value}")
                self.assertTrue(result.ok, result.output)
                self.assertEqual(result.output, f"register dump: {value}")
                self.assertEqual(dispatcher.dump.enabled, value == "on")

    def test_showdump_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":showdump OFF")
            self.assertTrue(result.ok)
            self.assertFalse(dispatcher.dump.enabled)

    def test_showdump_invalid_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":showdump maybe")
            self.assertFalse(result.ok)

    def test_showdump_too_many_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":showdump on off")
            self.assertFalse(result.ok)

    def test_sci_lists_nothing_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":sci")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "no scenarios configured (create a config.yaml or pass --config)")

    def test_sci_add_without_config_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":sci add ball")
            self.assertFalse(result.ok)

    def test_sci_add_assigns_numbers_and_returns_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci add ball")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(
                result.commands,
                (
                    "w 1 574 2 W C L",
                    "w 2 576 2 W C L",
                    "w 3 580 2 W C L",
                    "w 4 582 2 W C L",
                ),
            )
            self.assertEqual(
                dispatcher.scenarios.aliases(),
                {1: "ball.x", 2: "ball.y", 3: "ball.vx", 4: "ball.vy"},
            )
            self.assertIn("ball.x", result.output)

    def test_sci_add_second_scenario_continues_numbering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            dispatcher.dispatch(":sci add ball")
            result = dispatcher.dispatch(":sci add player1")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(
                result.commands,
                (
                    "w 5 5C0 2 W L",
                    "w 6 5B6 2 W C L",
                    "w 7 5B8 2 W C L",
                    "w 8 5BE 1 W C L",
                ),
            )

    def test_sci_add_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci add *")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(len(result.commands), 8)
            self.assertEqual(dispatcher.scenarios.active_names(), ["ball", "player1"])

    def test_sci_list_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            dispatcher.dispatch(":sci add ball")
            result = dispatcher.dispatch(":sci")
            self.assertTrue(result.ok)
            self.assertIn("active scenarios:", result.output)
            self.assertIn("ball: 1=ball.x, 2=ball.y, 3=ball.vx, 4=ball.vy", result.output)

    def test_sci_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            dispatcher.dispatch(":sci add ball")
            result = dispatcher.dispatch(":sci rm ball")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(result.commands, ("w 1", "w 2", "w 3", "w 4"))
            self.assertEqual(dispatcher.scenarios.aliases(), {})
            self.assertEqual(dispatcher.scenarios.active_names(), [])

    def test_sci_remove_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            dispatcher.dispatch(":sci add *")
            result = dispatcher.dispatch(":sci rm *")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(len(result.commands), 8)
            self.assertEqual(result.commands[0], "w 1")
            self.assertEqual(dispatcher.scenarios.active_names(), [])

    def test_sci_remove_all_when_none_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci rm *")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "no active scenarios")

    def test_sci_unknown_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci add nope")
            self.assertFalse(result.ok)
            self.assertIn("unknown scenario", result.output)

    def test_sci_remove_inactive_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci rm ball")
            self.assertFalse(result.ok)

    def test_sci_requires_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci add")
            self.assertFalse(result.ok)

    def test_sci_star_must_be_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp, ball_registry())
            result = dispatcher.dispatch(":sci add ball *")
            self.assertFalse(result.ok)

    def test_quit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":quit")
            self.assertTrue(result.quit)


if __name__ == "__main__":
    unittest.main()
