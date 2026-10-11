# Changelog

All notable changes to this project are documented in this file.  The format is loosely based on [Keep a Changelog](https://keepachangelog.com/), and the project aims to follow [Semantic Versioning](https://semver.org/).

Add a short entry under `Unreleased` for every completed feature or behavioural change, as described in `AGENTS.md` → Documentation.  Newest first.

## [Unreleased]

### Added

- `prompt_toolkit`-based interactive input line with cursor movement (Left/Right), Home/End, Backspace/Delete, and in-memory command history; debugger output is rendered above the prompt with `patch_stdout()`, so asynchronous output cannot corrupt the line being typed.
- Tab completion for shell command names and their parameters (`:output` choices, `:logfile` paths).
- `:output shell|log|both` to route all watchpoint hits to the screen, the CSV log, or both (default `shell`). In `log` mode the watchpoint hit block is hidden on the terminal and a fixed-position status line shows a logged-event counter per watchpoint.
- `:logfile <file>` to choose the CSV log file name. The default is `output_<timestamp>.csv` (milliseconds, so defaults never collide); the file is created lazily on the first logged hit, and an existing user-supplied name gets an increasing numeric suffix.
- Parser support for both the original watchpoint-hit output and FS-UAE's enhanced output (a leading hex counter and no `break at`).
- A `frame` column in the CSV log, holding the enhanced hit output's leading frame counter parsed as a decimal integer and left empty for the original format.

### Changed

- Watchpoint logging is now global rather than per watchpoint; hits go to the screen, the CSV log, or both according to the current `:output` mode.
- The interactive prompt is rendered by `prompt_toolkit` as `> `, so the cursor sits after the prompt instead of on top of the debugger's `>` character.
- CSV timestamps no longer carry a timezone offset, and the `watchpoint` column is now headed `wp`.

## [0.1.0] - 2026-10-10

### Added

- Transparent interactive wrapper around the FS-UAE 3.3.0 console debugger: launches FS-UAE on a `pexpect` pseudo-terminal, forwards user input, and displays debugger output as it arrives.
- Wrapper commands with a configurable prefix (default `:`): `:help`, `:status`, `:quit`; all other input is forwarded to the debugger unchanged.
- Incremental parser for the debugger output formats confirmed on FS-UAE 3.3.0 (activation, watchpoint definition, watchpoint hit, prompt).
- CSV watchpoint logging: append-only, UTF-8, header written on a new/empty file, every record flushed immediately.
- Unit tests with real captured FS-UAE output fixtures.
- Documentation: `README.md`, `docs/architecture.md`, `docs/decisions.md`, and `docs/debug-shell-output.md`.
