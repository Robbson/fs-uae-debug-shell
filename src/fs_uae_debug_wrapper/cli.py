"""Command-line entry point for the FS-UAE debug wrapper."""

from __future__ import annotations

import argparse
import logging
import sys

from .app import Application
from .config import AppConfig

USAGE_EPILOG = """\
example:
  %(prog)s -- --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae

Press F12+D in the FS-UAE window to activate the debugger console.  Type
':help' at the debugger prompt to list wrapper commands.  FS-UAE command line
arguments must follow '--' so they are not interpreted by the wrapper."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fs-uae-debug-wrapper",
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


def parse_args(argv: list[str] | None = None) -> AppConfig:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    fsuae_args = list(namespace.fsuae_args)
    if fsuae_args and fsuae_args[0] == "--":
        fsuae_args = fsuae_args[1:]
    return AppConfig(
        executable=namespace.fsuae,
        fsuae_args=fsuae_args,
        prefix=namespace.prefix,
        verbose=namespace.verbose,
    )


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    configure_logging(config.verbose)
    if not config.fsuae_args:
        logging.getLogger("fs_uae_debug_wrapper").warning(
            "no FS-UAE arguments supplied; FS-UAE will start with its defaults"
        )
    return Application(config).run()


if __name__ == "__main__":
    raise SystemExit(main())
