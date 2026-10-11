# FS-UAE Debug Wrapper

An interactive Python wrapper around the **FS-UAE console debugger** (tested against **FS-UAE 3.2.35** on Linux).  It keeps the native debugger fully usable while adding automation for memory watchpoints: parsing debugger output, appending watchpoint hits to CSV files, and automatically resuming emulation after a configured hit.

The wrapper is an automation layer built on top of the existing debugger.  It does not reimplement or reinterpret native debugger commands.

## Requirements

- Linux with a POSIX terminal
- [uv](https://docs.astral.sh/uv/)
- FS-UAE 3.2.35 (`fs-uae` on `PATH`) and a working X display (`DISPLAY`)

## Install

```sh
uv sync
```

## Usage

Launch FS-UAE through the wrapper, passing the FS-UAE arguments after `--`:

```sh
uv run main.py -- --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae
```

FS-UAE starts the emulator normally.  The debugger is **not** active at startup, so the wrapper cannot interact until you activate it:

1. When the game is running, press **F12 + D** in the FS-UAE window.
2. FS-UAE prints `WARNING: Activated debugger`, a register dump, and the interactive `>` prompt.  From here the debugger behaves as usual.

Wrapper-specific commands use the reserved prefix `:` (configurable with `--prefix`).  They are intercepted by the wrapper and never reach the emulator; every other line is forwarded to FS-UAE unchanged.

The input line is provided by [`prompt_toolkit`](https://python-prompt-toolkit.readthedocs.io/), so it supports cursor movement (Left/Right), Home/End, Backspace/Delete, and command history with the Up/Down arrows.  History is kept in memory for the current session.

### Options

```
--fsuae PATH             FS-UAE executable to launch (default: fs-uae)
--prefix CHAR            wrapper command prefix (default: :)
--no-auto-resume         start with automatic resume disabled
--show-watchpoint-dump   also print the debugger register dump on watchpoint hits
-v, --verbose            debug-level wrapper diagnostics
```

## Wrapper commands

| Command | Description |
| --- | --- |
| `:help` | Show the command list. |
| `:status` | Show state, resume/dump settings, logging watchpoints, and debugger watchpoints. |
| `:logwatch <id> <file>` | Log hits of watchpoint `<id>` to CSV `<file>`. |
| `:logoff <id>` | Stop logging watchpoint `<id>`. |
| `:wwcl <spec>[, ...]` | Create write-change watchpoints and log only changed values (see below). |
| `:wwcl` | List the write-change watchpoints and their last values. |
| `:auto on\|off\|toggle` | Enable/disable automatic resume after logging. |
| `:quit` | Stop the emulator and exit the wrapper. |

## Watch write change watchpoints (`:wwcl`)

`:wwcl` is a shortcut for creating a memory watch and logging only real changes.  Each entry is `<id> <name> <address> <length>`, and several entries can be comma-separated:

```text
:wwcl #1 ball.x 574 2, #2 ball.y 576 2
```

It sends one native `w` command per entry and enables logging automatically:

- `<id>` may be written as `1` or `#1`; the `#` is dropped before the `w` command.
- `<address>` is interpreted as hexadecimal (`574`, `$574` and `0x574` are all accepted).
- `<length>` is the watch length in bytes, as in the debugger's `w` command.
- `<name>` is a wrapper-only alias (letters, digits, `.`, `_`, `-`); it becomes the `name` column in the CSV.

The log file is named after the watches and a counter, e.g. `ball.x_ball.y_000.csv`, in the wrapper's working directory.  Each `:wwcl` call picks the next free number, so a new session starts a new file.  For example the call above logs to `ball.x_ball.y_000.csv` (then `_001.csv`, ...).

Values are de-duplicated per watch: a hit whose value equals the last recorded value of that watch is **not** logged and its `Memwatch ...` line is not printed, so the log and the terminal show only changes.  Emulation is still resumed for those hits.  As with `:logwatch`, a separate `g` is needed to start emulation; automatic resume then continues.

`:wwcl` with no arguments lists the watchpoints, their names, addresses, lengths, and last values.

## Watchpoint logging workflow

Watchpoints are created with the native debugger command `w` (see the debugger's own `help`).  The wrapper only *observes* them:

```text
w 0 $574 2 W
Memwatch breakpoints enabled
 0: 00000574 - 00000575 (2)  W  CPU
:logwatch 0 score.csv
[wrapper] logging watchpoint 0 to /path/to/score.csv
g
```

From then on, every hit of watchpoint 0 is appended to `score.csv` and, with automatic resume enabled, `g` is sent to continue emulation.  A hit looks like this in the debugger console (confirmed against FS-UAE 3.2.35):

```text
Memwatch 0: break at 00000574.W  W  000000FB PC=0000B8A6 CPUDW (000)
```

By default only the `Memwatch ... break at ...` line is shown for hits that are logged and automatically resumed; the debugger's register dump/disassembly and the wrapper's own per-hit summary are hidden so the terminal is not flooded on every iteration.  `--show-watchpoint-dump` also prints the register dump and the wrapper summary.  A hit that is not being logged, a manual debugger activation (F12+D), and `:auto off` always show the full output.

### Automatic resume safety

- `g` is sent **only** after a hit of an explicitly configured watchpoint is parsed *and* written to its CSV file successfully.
- A manual debugger activation (`WARNING: Activated debugger`), a breakpoint, or an exception does **not** trigger automatic resume.
- If logging fails, the emulator is left stopped and the error is reported.
- If you are in the middle of typing when a hit is handled, automatic resume is skipped and control stays with you.
- `:auto off` (or `--no-auto-resume`) disables the feature and returns to manual control.

## Log file format

CSV, UTF-8, append-only.  A header row is written when the file is created or empty.  Records are flushed immediately.

```text
timestamp,wp,name,address,size,access,value,pc
2026-10-10T21:14:35.165,0,ball.x,0x00000574,W,W,0x00000080,0x0000C28C
```

| Column | Meaning |
| --- | --- |
| `timestamp` | ISO-8601 local time, without a timezone offset. |
| `wp` | Watchpoint id from the `Memwatch <n>:` line. |
| `name` | Watch alias from `:wwcl`; empty for `:logwatch` watches. |
| `address` | Watchpoint address (hex). |
| `size` | Access size as printed by the debugger (`B`/`W`/`L`). |
| `access` | Access type as printed by the debugger (`R`/`W`/`I`/`F`/`C`). |
| `value` | Value printed by the debugger (hex). |
| `pc` | Program counter at the break (hex). |

Only fields present in the debugger's `Memwatch ...` line are recorded; the wrapper never fabricates values.

## Launch and attachment model

The wrapper **launches** FS-UAE and owns its console.  Attaching to an already-running FS-UAE process is not supported: the debugger console is bound to the terminal FS-UAE was started from, and FS-UAE provides no way to attach to it afterwards.  Always start FS-UAE through the wrapper.

If the wrapper's terminal goes away, the wrapper shuts down and terminates the FS-UAE child process so no emulator is left running unintentionally.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — module map, state model, data flow.
- [`docs/decisions.md`](docs/decisions.md) — why the structure and behaviour are as they are.
- [`docs/fs-uae-debugger-output.md`](docs/fs-uae-debugger-output.md) — the exact output formats captured from real FS-UAE 3.2.35 sessions, including the raw fixtures used by the parser tests.
- [`CHANGELOG.md`](CHANGELOG.md) — what has changed.

## Testing

Unit tests (no emulator required):

```sh
uv run python -m unittest discover -s tests
```

They cover parsing (including partial/multi-line output), command dispatch, watchpoint management, CSV creation/append/error handling, resume decisions, unrelated stops, logging failures, console input state, child-output handling, watchpoint output filtering, `:wwcl` parsing/validation, and change filtering.  Parser tests use real captured output in `tests/fixtures/`.

The full interactive flow was run end-to-end against a real FS-UAE 3.2.35 session (`--load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae`, watchpoint `$574`): a scripted PTY harness set the watchpoint, ran `:logwatch 0 score.csv`, resumed with `g`, observed consecutive watchpoint hits being logged and automatically resumed, and quit with `:quit`.  Every hit was logged exactly once and the emulator was left stopped on shutdown.  The only manual step was pressing F12+D to activate the debugger, which cannot be automated.

### Checks

- `uv run python -m unittest discover -s tests` — 99 tests, all passing.
- `uvx ruff check .` — clean.
- No type checker (mypy/pyright) is configured in this project.

## Known limitations

- Only output formats confirmed against FS-UAE 3.2.35 are parsed.  Other versions or WinUAE may differ.
- `:logwatch` watches are created with the native `w` command; `:wwcl` creates them for you.
- FS-UAE's watchpoint "must change" (`C`) flag does not work reliably, so `:wwcl` implements the change filter in the wrapper instead.
- Command history is kept in memory for the current session; it is not persisted across runs.
