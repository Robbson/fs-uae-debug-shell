from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_wrapper.commands import CommandDispatcher
from fs_uae_debug_wrapper.parser import WatchpointHit
from fs_uae_debug_wrapper.watchpoints import WatchpointManager


def make_hit(value: int, watchpoint: int = 0) -> WatchpointHit:
    return WatchpointHit(
        watchpoint=watchpoint,
        address=0x574,
        size="W",
        access="W",
        value=value,
        pc=0xC28C,
        trailer="CPUDW (000)",
        raw="Memwatch: break",
    )


def make_dispatcher(case: unittest.TestCase, tmp: str, auto: bool = True):
    manager = WatchpointManager()
    case.addCleanup(manager.close)
    state = {"auto": auto}

    def status() -> str:
        return "state: stopped"

    dispatcher = CommandDispatcher(
        prefix=":",
        manager=manager,
        status_provider=status,
        auto_resume_get=lambda: state["auto"],
        auto_resume_set=lambda value: state.__setitem__("auto", value),
        base_dir=Path(tmp),
    )
    return dispatcher, manager, state


class CommandDispatcherTests(unittest.TestCase):
    def test_handles_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            self.assertTrue(dispatcher.handles(":help"))
            self.assertFalse(dispatcher.handles("r"))
            self.assertFalse(dispatcher.handles("g"))

    def test_help(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":help")
            self.assertTrue(result.ok)
            self.assertIn("wrapper commands", result.output)

    def test_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":status")
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "state: stopped")

    def test_unknown_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":bogus")
            self.assertFalse(result.ok)
            self.assertIn("unknown command", result.output)

    def test_empty_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":")
            self.assertFalse(result.ok)

    def test_logwatch_and_logoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch 0 score.csv")
            self.assertTrue(result.ok, result.output)
            self.assertIsNotNone(manager.get(0))

            result = dispatcher.dispatch(":logoff 0")
            self.assertTrue(result.ok)
            self.assertIsNone(manager.get(0))

    def test_logwatch_invalid_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch notanumber score.csv")
            self.assertFalse(result.ok)

    def test_logwatch_wrong_arity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch 0")
            self.assertFalse(result.ok)

    def test_logwatch_bad_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logwatch 0 missing/score.csv")
            self.assertFalse(result.ok)

    def test_logoff_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":logoff 9")
            self.assertFalse(result.ok)

    def test_logwatch_relative_resolves_to_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            dispatcher.dispatch(":logwatch 1 sub.csv")
            config = manager.get(1)
            assert config is not None
            self.assertEqual(config.path, Path(tmp) / "sub.csv")

    def test_auto_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, state = make_dispatcher(self, tmp, auto=True)
            result = dispatcher.dispatch(":auto off")
            self.assertTrue(result.ok)
            self.assertFalse(state["auto"])
            dispatcher.dispatch(":auto on")
            self.assertTrue(state["auto"])
            dispatcher.dispatch(":auto toggle")
            self.assertFalse(state["auto"])

    def test_auto_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":auto maybe")
            self.assertFalse(result.ok)

    def test_quit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":quit")
            self.assertTrue(result.quit)

    def test_quoted_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(':logwatch 0 "my log.csv"')
            self.assertTrue(result.ok, result.output)
            config = manager.get(0)
            assert config is not None
            self.assertEqual(config.path.name, "my log.csv")


class WwclCommandTests(unittest.TestCase):
    def test_single_watch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball.x 574 2")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(result.forward, ("w 1 $574 2 W",))
            watch = manager.get_watch(1)
            assert watch is not None
            self.assertEqual(watch.name, "ball.x")
            self.assertEqual(watch.address, 0x574)
            self.assertEqual(watch.length, 2)
            self.assertIsNotNone(manager.get(1))
            self.assertEqual(Path(tmp, "ball.x_000.csv").exists(), True)

    def test_multiple_watches_share_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball.x 574 2, #2 ball.y 576 2")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(result.forward, ("w 1 $574 2 W", "w 2 $576 2 W"))
            self.assertTrue(Path(tmp, "ball.x_ball.y_000.csv").exists())
            assert manager.get(1) is not None and manager.get(2) is not None
            self.assertEqual(manager.get(1).path, manager.get(2).path)

    def test_hash_prefix_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl 1 ball.x 574 2")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(result.forward, ("w 1 $574 2 W",))
            self.assertIsNotNone(manager.get_watch(1))

    def test_dollar_address_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball.x $574 2")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(result.forward, ("w 1 $574 2 W",))

    def test_counter_increments_per_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            dispatcher.dispatch(":wwcl #1 ball.x 574 2")
            dispatcher.dispatch(":wwcl #1 ball.x 574 2")
            self.assertTrue(Path(tmp, "ball.x_000.csv").exists())
            self.assertTrue(Path(tmp, "ball.x_001.csv").exists())

    def test_list_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl")
            self.assertTrue(result.ok)
            self.assertIn("no watch write change", result.output)

    def test_list_shows_names_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, manager, _ = make_dispatcher(self, tmp)
            dispatcher.dispatch(":wwcl #1 ball.x 574 2")
            manager.observe(make_hit(0x19, watchpoint=1))
            result = dispatcher.dispatch(":wwcl")
            self.assertTrue(result.ok)
            self.assertIn("#1 ball.x", result.output)
            self.assertIn("00000019", result.output)

    def test_invalid_arity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball.x 574")
            self.assertFalse(result.ok)

    def test_invalid_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball/x 574 2")
            self.assertFalse(result.ok)

    def test_invalid_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball.x zzz 2")
            self.assertFalse(result.ok)

    def test_invalid_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 ball.x 574 0")
            self.assertFalse(result.ok)

    def test_duplicate_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":wwcl #1 a 100 2, #1 b 200 2")
            self.assertFalse(result.ok)

    def test_help_mentions_wwcl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dispatcher, _, _ = make_dispatcher(self, tmp)
            result = dispatcher.dispatch(":help")
            self.assertIn("wwcl", result.output)


if __name__ == "__main__":
    unittest.main()
