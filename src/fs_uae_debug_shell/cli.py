"""Command-line entry point for the Debug Shell."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .app import Application
from .config import AppConfig
from .scenarios import ConfigError, ScenarioCatalog, load_scenarios

USAGE_EPILOG = """\
example:
  %(prog)s -- --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae

Press F12+D in the FS-UAE window to activate the debugger console.  Type
':help' at the debugger prompt to list wrapper commands.  FS-UAE command line
arguments must follow '--' so they are not interpreted by the wrapper."""

DEFAULT_CONFIG_NAME = "config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fs-uae-debug-shell",
        description="Interactive wrapper around the FS-UAE console debugger.",
        epilog=USAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fsuae",
        default="fs-uae",
        metavar="PATH",
        help="FS-UAE executable to launch (default: %(default)s)",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=f"watchpoint scenario file (default: ./{DEFAULT_CONFIG_NAME} when present)",
    )
    parser.add_argument(
        "--prefix",
        default=":",
        metavar="CHAR",
        help="wrapper command prefix (default: %(default)s)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug-level wrapper diagnostics",
    )
    parser.add_argument(
        "fsuae_args",
        nargs=argparse.REMAINDER,
        metavar="-- FSUAE-ARGS",
        help="arguments passed to FS-UAE unchanged",
    )
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[wrapper] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def resolve_config_path(explicit: str | None, cwd: Path) -> Path | None:
    """Return the config file to load, or ``None`` when there is nothing to load.

    An explicitly requested path must exist; a missing default file simply means
    the scenario feature stays inert.
    """

    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"scenario config not found: '{path}'")
        return path
    candidate = cwd / DEFAULT_CONFIG_NAME
    return candidate if candidate.is_file() else None


def parse_args(argv: list[str] | None = None, cwd: Path | None = None) -> AppConfig:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    fsuae_args = list(namespace.fsuae_args)
    if fsuae_args and fsuae_args[0] == "--":
        fsuae_args = fsuae_args[1:]
    path = resolve_config_path(namespace.config, (cwd or Path.cwd()))
    scenarios = load_scenarios(path) if path is not None else ScenarioCatalog.empty()
    return AppConfig(
        executable=namespace.fsuae,
        fsuae_args=fsuae_args,
        prefix=namespace.prefix,
        verbose=namespace.verbose,
        scenarios=scenarios,
        config_path=str(path) if path is not None else None,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(argv)
    except ConfigError as exc:
        sys.stderr.write(f"[wrapper] error: {exc}\n")
        return 2
    configure_logging(config.verbose)
    if not config.fsuae_args:
        logging.getLogger("fs_uae_debug_shell").warning(
            "no FS-UAE arguments supplied; FS-UAE will start with its defaults"
        )
    return Application(config).run()


if __name__ == "__main__":
    raise SystemExit(main())
