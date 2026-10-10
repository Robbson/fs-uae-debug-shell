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

### Options

```
--fsuae PATH        FS-UAE executable to launch (default: fs-uae)
--prefix CHAR       wrapper command prefix (default: :)
--no-auto-resume    start with automatic resume disabled
-v, --verbose       debug-level wrapper diagnostics
```

## Wrapper commands

| Command | Description |
| --- | --- |
| `:help` | Show the command list. |
| `:status` | Show debugger state, logging watchpoints, and debugger watchpoints. |
| `:logwatch <id> <file>` | Log hits of watchpoint `<id>` to CSV `<file>`. |
| `:logoff <id>` | Stop logging watchpoint `<id>`. |
| `:auto on\|off\|toggle` | Enable/disable automatic resume after logging. |
| `:quit` | Stop the emulator and exit the wrapper. |

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

### Automatic resume safety

- `g` is sent **only** after a hit of an explicitly configured watchpoint is parsed *and* written to its CSV file successfully.
- A manual debugger activation (`WARNING: Activated debugger`), a breakpoint, or an exception does **not** trigger automatic resume.
- If logging fails, the emulator is left stopped and the error is reported.
- If you are in the middle of typing when a hit is handled, automatic resume is skipped and control stays with you.
- `:auto off` (or `--no-auto-resume`) disables the feature and returns to manual control.

## Log file format

CSV, UTF-8, append-only.  A header row is written when the file is created or empty.  Records are flushed immediately.

```text
timestamp,watchpoint,address,size,access,value,pc
2026-10-10T21:14:35.165+02:00,0,0x00000574,W,W,0x00000080,0x0000C28C
```

| Column | Meaning |
| --- | --- |
| `timestamp` | ISO-8601 local time with offset. |
| `watchpoint` | Watchpoint id from the `Memwatch <n>:` line. |
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

They cover parsing (including partial/multi-line output), command dispatch, watchpoint management, CSV creation/append/error handling, resume decisions, unrelated stops, and logging failures.  Parser tests use real captured output in `tests/fixtures/`.

The automatic-resume pipeline (activate debugger → set watchpoint → `:logwatch` → repeated hits logged and resumed → CSV written → `:quit`) was also verified against a real FS-UAE 3.2.35 session with the game `--load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae` and watchpoint `$574`.  Integration requires a human to press F12+D once; there is no programmatic way to activate the debugger at startup.

### Checks

- `uv run python -m unittest discover -s tests` — 51 tests, all passing.
- `uvx ruff check .` — clean.
- No type checker (mypy/pyright) is configured in this project.

## Known limitations

- Only output formats confirmed against FS-UAE 3.2.35 are parsed.  Other versions or WinUAE may differ.
- Watchpoints themselves are created with the native `w` command; the wrapper does not create them.
- The debugger does not support readline-style line editing (the kernel echo is on in a normal session), so the wrapper's local line editing is limited to printable input and backspace.
