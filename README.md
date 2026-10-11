# Debug Shell for FS-UAE

An interactive Python wrapper around the **FS-UAE console debugger** on Linux. Only the forked FS-UAE version 3.3.0 and above is supported because it has mandatory fixes to make the wrapper work. It keeps the native debugger fully usable while adding automation for memory watchpoints: parsing debugger output and appending watchpoint hits to CSV files.

The wrapper is an automation layer built on top of the existing debugger. It does not reimplement or reinterpret native debugger commands.

## Requirements

- Linux with a POSIX terminal
- [uv](https://docs.astral.sh/uv/)
- FS-UAE >=3.3.3 (`fs-uae` on `PATH`) and a working X display (`DISPLAY`)

## Install

```sh
uv sync
```

## Usage

//TODO: Change the sample here as well, including the save sate

Launch FS-UAE through the wrapper, passing the FS-UAE arguments after `--`:

```sh
uv run main.py -- --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae
```

FS-UAE starts the emulator normally. The debugger is **not** active at startup, so the wrapper cannot interact until you activate it:

1. When the game is running, press **F12 + D** in the FS-UAE window.
2. FS-UAE prints `WARNING: Activated debugger`, a register dump, and the interactive `>` prompt.
From here the debugger behaves as usual.

Wrapper-specific commands use the reserved prefix `:` (configurable with `--prefix`). They are intercepted by the wrapper and never reach the emulator; every other line is forwarded to FS-UAE unchanged.

The input line is provided by [`prompt_toolkit`](https://python-prompt-toolkit.readthedocs.io/), so it supports cursor movement (Left/Right), Home/End, Backspace/Delete, and command history with the Up/Down arrows. History is kept in memory for the current session.

### Options

```
--fsuae PATH             FS-UAE executable to launch (default: fs-uae)
--prefix CHAR            wrapper command prefix (default: :)
-v, --verbose            debug-level wrapper diagnostics
```

## Wrapper commands

| Command | Description |
| --- | --- |
| `:help` | Show the command list. |
| `:status` | Show state, logging watchpoints, and debugger watchpoints. |
| `:logwatch <id> <file>` | Log hits of watchpoint `<id>` to CSV `<file>`. |
| `:logoff <id>` | Stop logging watchpoint `<id>`. |
| `:quit` | Stop the emulator and exit the wrapper. |

## Watchpoint logging workflow

Watchpoints are created with the native debugger command `w` (see the debugger's own `help`). The wrapper only *observes* them:

```text
w 0 $574 2 W
Memwatch breakpoints enabled
 0: 00000574 - 00000575 (2)  W  CPU
:logwatch 0 score.csv
[wrapper] logging watchpoint 0 to /path/to/score.csv
g
```

From then on, every hit of watchpoint 0 is appended to `score.csv`. A hit looks like this in the debugger console (confirmed against FS-UAE 3.2.35):

```text
Memwatch 0: break at 00000574.W  W  000000FB PC=0000B8A6 CPUDW (000)
```

A watchpoint hit stops the emulator at the debugger prompt, exactly as the native debugger does. The wrapper logs the hit and leaves control with you; emulation continues only when you send `g` (or another command) yourself.

## Log file format

CSV, UTF-8, append-only. A header row is written when the file is created or empty. Records are flushed immediately.

```text
timestamp,wp,address,size,access,value,pc
2026-10-10T21:14:35.165,0,0x00000574,W,W,0x00000080,0x0000C28C
```

| Column | Meaning |
| --- | --- |
| `timestamp` | ISO-8601 local time, without a timezone offset. |
| `wp` | Watchpoint id from the `Memwatch <n>:` line. |
| `address` | Watchpoint address (hex). |
| `size` | Access size as printed by the debugger (`B`/`W`/`L`). |
| `access` | Access type as printed by the debugger (`R`/`W`/`I`/`F`/`C`). |
| `value` | Value printed by the debugger (hex). |
| `pc` | Program counter at the break (hex). |

Only fields present in the debugger's `Memwatch ...` line are recorded; the wrapper never fabricates values.

## Launch and attachment model

The wrapper **launches** FS-UAE and owns its console. Attaching to an already-running FS-UAE process is not supported: the debugger console is bound to the terminal FS-UAE was started from, and FS-UAE provides no way to attach to it afterwards. Always start FS-UAE through the wrapper.

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

They cover parsing (including partial/multi-line output), command dispatch, watchpoint management, CSV creation/append/error handling, console input state, and child-output handling. Parser tests use real captured output in `tests/fixtures/`.

### Checks

- `uv run python -m unittest discover -s tests` — 60 tests, all passing.
- `uvx ruff check .` — clean.
- No type checker (mypy/pyright) is configured in this project.

## Known limitations

- Only output formats confirmed against FS-UAE 3.3.0 or higher are parsed. Other versions or WinUAE differ.
- Watchpoints are created with the native `w` command; the wrapper does not create them for you.
- Command history is kept in memory for the current session; it is not persisted across runs.
