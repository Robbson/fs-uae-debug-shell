from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fs_uae_debug_shell.scenarios import (
    ConfigError,
    ScenarioCatalog,
    WatchpointRegistry,
    load_scenarios,
    parse_scenarios,
)

FIXTURES = Path(__file__).parent / "fixtures"


class LoadScenariosTests(unittest.TestCase):
    def test_fixture_loads_defaults_and_overrides(self) -> None:
        catalog = load_scenarios(FIXTURES / "config.yaml")
        self.assertEqual(catalog.names(), ["ball", "player1"])
        ball = catalog.get("ball")
        assert ball is not None
        self.assertEqual(
            [(e.name, e.address, e.length, e.flags) for e in ball.entries],
            [
                ("ball.x", "574", 2, ("W", "C", "L")),
                ("ball.y", "576", 2, ("W", "C", "L")),
                ("ball.vx", "580", 2, ("W", "C", "L")),
                ("ball.vy", "582", 2, ("W", "C", "L")),
            ],
        )
        player1 = catalog.get("player1")
        assert player1 is not None
        self.assertEqual(player1.entries[0].flags, ("W", "L"))
        self.assertEqual(player1.entries[1].length, 2)
        self.assertEqual(player1.entries[3].length, 1)

    def test_empty_file_is_an_empty_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("", encoding="utf-8")
            self.assertEqual(load_scenarios(path).names(), [])

    def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ConfigError):
            load_scenarios(Path(tmp) / "nope.yaml")

    def test_invalid_yaml_raises_with_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("memwatch: [unclosed\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_scenarios(path)
            self.assertIn(str(path), str(ctx.exception))


class ValidationTests(unittest.TestCase):
    def fail(self, data: object) -> str:
        with self.assertRaises(ConfigError) as ctx:
            parse_scenarios(data, source="config.yaml")
        return str(ctx.exception)

    def test_document_must_be_mapping(self) -> None:
        self.assertIn("must be a mapping", self.fail([1, 2]))

    def test_unknown_top_level_key(self) -> None:
        self.assertIn("unknown key(s): nope", self.fail({"nope": {}}))

    def test_memwatch_must_be_mapping(self) -> None:
        self.assertIn("memwatch: must be a mapping", self.fail({"memwatch": 3}))

    def test_unknown_memwatch_key(self) -> None:
        self.assertIn("unknown key(s): wat", self.fail({"memwatch": {"wat": 1}}))

    def test_defaults_must_be_mapping(self) -> None:
        self.assertIn("memwatch.defaults: must be a mapping", self.fail({"memwatch": {"defaults": 1}}))

    def test_scenarios_must_be_mapping(self) -> None:
        self.assertIn(
            "memwatch.scenarios: must be a mapping",
            self.fail({"memwatch": {"scenarios": []}}),
        )

    def test_scenario_must_be_non_empty_list(self) -> None:
        self.assertIn(
            "memwatch.scenarios.ball: must be a non-empty list",
            self.fail({"memwatch": {"scenarios": {"ball": []}}}),
        )

    def test_entry_must_be_mapping(self) -> None:
        message = self.fail({"memwatch": {"scenarios": {"ball": [1]}}})
        self.assertIn("memwatch.scenarios.ball[0]: must be a mapping", message)

    def test_entry_unknown_key(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1", "x": 1}]}}}
        )
        self.assertIn("unknown key(s): x", message)

    def test_missing_name(self) -> None:
        message = self.fail({"memwatch": {"scenarios": {"ball": [{"address": "1"}]}}})
        self.assertIn("'name' is required", message)

    def test_invalid_name(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a b", "address": "1"}]}}}
        )
        self.assertIn("'name' must be", message)

    def test_missing_address(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a"}]}}}
        )
        self.assertIn("'address' is required", message)

    def test_invalid_address(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "xyz"}]}}}
        )
        self.assertIn("'address' must be a hexadecimal string", message)

    def test_address_as_integer_is_accepted(self) -> None:
        catalog = parse_scenarios(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": 574, "length": 2, "flags": ["W"]}]}}}
        )
        assert catalog.get("ball") is not None
        self.assertEqual(catalog.get("ball").entries[0].address, "574")

    def test_invalid_length(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1", "length": 0}]}}}
        )
        self.assertIn("'length' must be a positive integer", message)

    def test_boolean_length_rejected(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1", "length": True}]}}}
        )
        self.assertIn("'length' must be a positive integer", message)

    def test_missing_length_without_default(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1"}]}}}
        )
        self.assertIn("'length' is required", message)

    def test_flags_must_be_a_list(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1", "length": 2, "flags": "W"}]}}}
        )
        self.assertIn("'flags' must be a list", message)

    def test_empty_flags_rejected(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1", "length": 2, "flags": []}]}}}
        )
        self.assertIn("'flags' must not be empty", message)

    def test_missing_flags_without_default(self) -> None:
        message = self.fail(
            {"memwatch": {"scenarios": {"ball": [{"name": "a", "address": "1", "length": 2}]}}}
        )
        self.assertIn("'flags' is required", message)

    def test_duplicate_name_in_scenario(self) -> None:
        message = self.fail(
            {
                "memwatch": {
                    "scenarios": {
                        "ball": [
                            {"name": "a", "address": "1", "length": 2, "flags": ["W"]},
                            {"name": "a", "address": "2", "length": 2, "flags": ["W"]},
                        ]
                    }
                }
            }
        )
        self.assertIn("duplicate watchpoint name 'a'", message)


class WatchpointRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_scenarios(FIXTURES / "config.yaml")

    def test_add_assigns_numbers_and_aliases(self) -> None:
        registry = WatchpointRegistry(self.catalog)
        commands = registry.add("ball")
        self.assertEqual(
            commands,
            [
                "w 1 574 2 W C L",
                "w 2 576 2 W C L",
                "w 3 580 2 W C L",
                "w 4 582 2 W C L",
            ],
        )
        self.assertEqual(
            registry.aliases(),
            {1: "ball.x", 2: "ball.y", 3: "ball.vx", 4: "ball.vy"},
        )
        self.assertEqual(registry.active_names(), ["ball"])

    def test_numbering_continues_across_scenarios(self) -> None:
        registry = WatchpointRegistry(self.catalog)
        registry.add("ball")
        commands = registry.add("player1")
        self.assertEqual(
            commands,
            [
                "w 5 5C0 2 W L",
                "w 6 5B6 2 W C L",
                "w 7 5B8 2 W C L",
                "w 8 5BE 1 W C L",
            ],
        )

    def test_remove_returns_commands_and_clears_aliases(self) -> None:
        registry = WatchpointRegistry(self.catalog)
        registry.add("ball")
        commands = registry.remove("ball")
        self.assertEqual(commands, ["w 1", "w 2", "w 3", "w 4"])
        self.assertEqual(registry.aliases(), {})
        self.assertEqual(registry.active_names(), [])

    def test_alias_lookup(self) -> None:
        registry = WatchpointRegistry(self.catalog)
        registry.add("ball")
        self.assertEqual(registry.alias(1), "ball.x")
        self.assertIsNone(registry.alias(99))

    def test_assignment_reports_numbers_and_entries(self) -> None:
        registry = WatchpointRegistry(self.catalog)
        registry.add("ball")
        assignment = registry.assignment("ball")
        self.assertEqual(assignment[0][0], 1)
        self.assertEqual(assignment[0][1].name, "ball.x")

    def test_unknown_scenario_raises(self) -> None:
        registry = WatchpointRegistry(self.catalog)
        with self.assertRaises(KeyError):
            registry.add("nope")

    def test_empty_catalog_is_inert(self) -> None:
        registry = WatchpointRegistry()
        self.assertFalse(registry.configured)
        self.assertEqual(registry.names(), [])
        self.assertEqual(registry.aliases(), {})
        self.assertEqual(ScenarioCatalog.empty().names(), [])


if __name__ == "__main__":
    unittest.main()
