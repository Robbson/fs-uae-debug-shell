# Changelog

All notable changes to this project are documented in this file.  The format is loosely based on [Keep a Changelog](https://keepachangelog.com/), and the project aims to follow [Semantic Versioning](https://semver.org/).

Add a short entry under `Unreleased` for every completed feature or behavioural change, as described in `AGENTS.md` → Documentation.  Newest first.

## [Unreleased]

### Added

- `prompt_toolkit`-based interactive input line with cursor movement (Left/Right), Home/End, Backspace/Delete, and in-memory command history; debugger output is rendered above the prompt with `patch_stdout()`, so asynchronous output cannot corrupt the line being typed.

### Changed

- CSV timestamps no longer carry a timezone offset, and the `watchpoint` column is now headed `wp`.

## [0.1.0] - 2026-10-10

### Added

- Transparent interactive wrapper around the FS-UAE 3.3.0 console debugger: launches FS-UAE on a `pexpect` pseudo-terminal, forwards user input, and displays debugger output as it arrives.
- Wrapper commands with a configurable prefix (default `:`): `:help`, `:status`, `:logwatch`, `:logoff`, `:quit`; all other input is forwarded to the debugger unchanged.
- Incremental parser for the debugger output formats confirmed on FS-UAE 3.3.0 (activation, watchpoint definition, watchpoint hit, prompt).
- CSV watchpoint logging: append-only, UTF-8, header written on a new/empty file, every record flushed immediately.
- Unit tests with real captured FS-UAE output fixtures.
- Documentation: `README.md`, `docs/architecture.md`, `docs/decisions.md`, and `docs/debug-shell-output.md`.
