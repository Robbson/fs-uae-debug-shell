# Changelog

All notable changes to this project are documented in this file.  The format is loosely based on [Keep a Changelog](https://keepachangelog.com/), and the project aims to follow [Semantic Versioning](https://semver.org/).

Add a short entry under `Unreleased` for every completed feature or behavioural change, as described in `AGENTS.md` → Documentation.  Newest first.

## [Unreleased]

### Added

- `prompt_toolkit` as a runtime dependency.
- `--show-watchpoint-dump` to print the debugger register dump and the wrapper's per-hit summary for watchpoint hits.
- `:wwcl <id> <name> <address> <length>[, ...]` to create write-change watchpoints in one command, log them to an auto-named CSV file (`<name1>_<name2>_NNN.csv`), and de-duplicate unchanged values (FS-UAE's own `C` flag does not work).  `:wwcl` with no arguments lists the watches and their last values.
- A `name` column in the CSV, taken from `:wwcl` watch aliases (empty for `:logwatch` watches).

### Changed

- Replaced the hand-written line editor with a `prompt_toolkit` `PromptSession`, so the input line now supports cursor movement (Left/Right), Home/End, Backspace/Delete, and command history with the Up/Down arrows.
- The wrapper input loop now runs on `asyncio` and reads FS-UAE output with `loop.add_reader`; debugger output is rendered above the prompt via `patch_stdout()`, so asynchronous output no longer corrupts the line being typed.
- Watchpoint hits that are logged and automatically resumed now show only the `Memwatch ... break at ...` line by default; the register dump/disassembly and the wrapper's per-hit summary are suppressed.  Use `--show-watchpoint-dump` for the previous verbose output.
- CSV timestamps no longer carry a timezone offset, and the `watchpoint` column is now headed `wp`.

## [0.1.0] - 2026-10-10

### Added

- Transparent interactive wrapper around the FS-UAE 3.2.35 console debugger: launches FS-UAE on a `pexpect` pseudo-terminal, forwards user input, and displays debugger output as it arrives.
- Wrapper commands with a configurable prefix (default `:`): `:help`, `:status`, `:logwatch`, `:logoff`, `:auto`, `:quit`; all other input is forwarded to the debugger unchanged.
- Incremental parser for the debugger output formats confirmed on FS-UAE 3.2.35 (activation, watchpoint definition, watchpoint hit, prompt).
- CSV watchpoint logging: append-only, UTF-8, header written on a new/empty file, every record flushed immediately.
- Safe automatic resume for configured watchpoint hits only, gated on a successful parse and log and on the debugger prompt, and skipped when the user is typing.
- Unit tests with real captured FS-UAE output fixtures.
- Documentation: `README.md`, `docs/architecture.md`, `docs/decisions.md`, and `docs/fs-uae-debugger-output.md`.
