# Changelog

All notable changes to this project are documented in this file.  The format is loosely based on [Keep a Changelog](https://keepachangelog.com/), and the project aims to follow [Semantic Versioning](https://semver.org/).

Add a short entry under `Unreleased` for every completed feature or behavioural change, as described in `AGENTS.md` → Documentation.  Newest first.

## [Unreleased]

### Added

- Quick watchpoints by address: a `:` followed by comma-separated hexadecimal addresses (`:574, 576, 580`) adds them directly, applying `memwatch.defaults` from `config.yaml`, aliasing each by its bare address and generating the native `w` commands. An optional length override may follow an address (`:574, 576 4, 580`); flags always come from the defaults. No command is provided to remove them — use the debugger's own `w`. This is the only place `memwatch.defaults` are used without a scenario, so a defaults-only `config.yaml` is now accepted.
- `--startdebug [MS]` (default off) starts FS-UAE with its debugger already active: the wrapper adds `--console_debugger=1 --debugger_signal=1 --stdout` (leaving any you supplied unchanged) and sends `SIGUSR1` once the forked build prints its signal-ready marker, so the shell prompt is available from the very beginning instead of waiting for F12+D. An optional delay in milliseconds postpones the signal (measured from the marker) so the emulator can run past a still-loading level first.
- `:showdump on|off` (default `on`) to show or hide the CPU register dump the debugger prints whenever it stops (on a manual activation or a watchpoint break). The dump block is recognised by its `-- stub -- activate_console` and `Next PC:` boundaries and hidden on the terminal only; the introducing `WARNING: Activated debugger` / `Memwatch ...` lines, the log, and the untagged dump of the `r` command are unaffected.
- Watchpoint scenarios: `config.yaml` (path overridable with `--config`) defines named watchpoints under `memwatch.scenarios`, with shared `memwatch.defaults` for `length` and `flags`; the file is validated at startup and a broken file aborts the wrapper with a located message. A `config.schema.json` is included for editor validation.
- `:sci add|rm <scenario>...` to activate or remove scenarios (`*` selects every scenario; no argument lists the active ones). Scenarios are numbered automatically from the last used number, and the wrapper generates and sends the native `w` commands for you (add: `w <num> <address> <length> <flags>`; remove: `w <num>`).
- Watchpoint aliases (the scenario entry names) replace the numbers in the wrapper's own output: the condensed frame row, the CSV log (per-hit `wp` cells and wide per-frame headers), the status line and `:status`. Verbatim debugger lines are never rewritten.
- `:frameagg on|off` (default `on`) condenses the selected hits of each video frame into one row that keeps only the frame counter, the watchpoint ids, and their values, for both the terminal and the CSV log. The CSV log uses a wide per-frame schema (`timestamp,frame,wp1,wp2,...`) with one column per watchpoint and an empty cell for a watchpoint that did not write in the frame; the classic output without a frame counter ignores the setting.
- `:framevalues first|last|all` to choose which write of each video frame and watchpoint is shown and logged for FS-UAE's enhanced hit output (which carries a frame counter); the default is `first`, and the classic output without a frame counter ignores the setting.
- `prompt_toolkit`-based interactive input line with cursor movement (Left/Right), Home/End, Backspace/Delete, and in-memory command history; debugger output is rendered above the prompt with `patch_stdout()`, so asynchronous output cannot corrupt the line being typed.
- Tab completion for shell command names and their parameters (`:output` choices, `:logfile` paths, configured scenario names for `:sci`).
- `:output shell|log|both` to route all watchpoint hits to the screen, the CSV log, or both (default `shell`). In `log` mode the watchpoint hit block is hidden on the terminal and a fixed-position status line shows a logged-event counter per watchpoint.
- `:logfile <file>` to choose the CSV log file name. The default is `output_<timestamp>.csv` (milliseconds, so defaults never collide); the file is created lazily on the first logged hit, and an existing user-supplied name gets an increasing numeric suffix.
- Parser support for both the original watchpoint-hit output and FS-UAE's enhanced output (a leading frame counter and no `break at`).
- A `frame` column in the CSV log, holding the enhanced hit output's leading frame counter parsed as a decimal integer and left empty for the original format.

### Changed

- Watchpoint logging is now global rather than per watchpoint; hits go to the screen, the CSV log, or both according to the current `:output` mode.
- The interactive prompt is rendered by `prompt_toolkit` as `> `, so the cursor sits after the prompt instead of on top of the debugger's `>` character.
- In `shell`/`both` mode the interactive prompt is raised only while the debugger is idle at its `>` prompt. Output produced while emulation runs or while a forwarded command is executing is written directly to the terminal instead of being erased and repainted above a prompt, so dumps and watchpoint-hit streams no longer arrive in slow, debounced pulses.
- In `log` mode the prompt and its status line stay up while the game runs, so the per-watchpoint counter remains visible and updates on every logged hit; the hit block is hidden there, so nothing needs repainting.
- Output from a single PTY read is written to the terminal in one batch rather than one write per parsed line.
- CSV timestamps no longer carry a timezone offset, and the `watchpoint` column is now headed `wp`.
- The CSV log now has two schemas: the per-hit `timestamp,frame,wp,address,size,access,value,pc` schema, and, with `:frameagg on`, a wide per-frame `timestamp,frame,wp1,wp2,...` schema. The schema is fixed when the file is created, so changing the output shape while a file is open starts a new file.

### Fixed

- The incremental parser no longer re-copies its buffer for every line, so a large output chunk is parsed in a single pass instead of quadratic time.

## [0.1.0] - 2026-10-10

### Added

- Transparent interactive wrapper around the FS-UAE 3.3.0 console debugger: launches FS-UAE on a `pexpect` pseudo-terminal, forwards user input, and displays debugger output as it arrives.
- Wrapper commands with a configurable prefix (default `:`): `:help`, `:status`, `:quit`; all other input is forwarded to the debugger unchanged.
- Incremental parser for the debugger output formats confirmed on FS-UAE 3.3.0 (activation, watchpoint definition, watchpoint hit, prompt).
- CSV watchpoint logging: append-only, UTF-8, header written on a new/empty file, every record flushed immediately.
- Unit tests with real captured FS-UAE output fixtures.
- Documentation: `README.md`, `docs/architecture.md`, `docs/decisions.md`, and `docs/debug-shell-output.md`.
