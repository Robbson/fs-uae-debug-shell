# Debug Shell for FS-UAE

An interactive Python wrapper around the **FS-UAE console debugger** on Linux. Only the forked FS-UAE version 3.3.0 and above is supported because it has mandatory fixes to make the wrapper work. It keeps the native debugger fully usable while adding automation for memory watchpoints: parsing debugger output and logging watchpoint hits to a CSV file.

The wrapper is an automation layer built on top of the existing debugger. It does not reimplement or reinterpret native debugger commands.

## Requirements

- Linux with a POSIX terminal
- [uv](https://docs.astral.sh/uv/)
- FS-UAE >=3.3.0 (`fs-uae` on `PATH`) and a working X display (`DISPLAY`)

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
2. FS-UAE prints `WARNING: Activated debugger`, a register dump, and the interactive `>` prompt; the wrapper raises its own `> ` prompt at that point.

From here the debugger behaves as usual. While the game is running FS-UAE's debugger accepts no console input, so the wrapper shows no prompt, and debugger output is written straight to the terminal rather than repainted above an active prompt.

Shell-specific commands use the reserved prefix `:` (configurable with `--prefix`). They are intercepted by the wrapper and never reach the emulator; every other line is forwarded to FS-UAE unchanged.

The input line is provided by [`prompt_toolkit`](https://python-prompt-toolkit.readthedocs.io/), so it supports cursor movement (Left/Right), Home/End, Backspace/Delete, and command history with the Up/Down arrows. Press **Tab** for completion of shell command names and their parameters (`:output shell|log|both`, `:logfile` paths). History is kept in memory for the current session. In `shell`/`both` mode the prompt is shown only while the debugger is at its `>` prompt; in `log` mode it stays up while the game runs so the status line keeps showing progress. Shell commands (including `:quit`) are available once the debugger is active.

### Options

```
--fsuae PATH             FS-UAE executable to launch (default: fs-uae)
--prefix CHAR            shell command prefix (default: :)
-v, --verbose            debug-level wrapper diagnostics
```

## Shell commands

| Command | Description |
| --- | --- |
| `:help` | Show the command list. |
| `:status` | Show debugger state, output mode, log file, and counters. |
| `:output shell\|log\|both` | Route all watchpoint hits (default: `shell`). |
| `:logfile <file>` | Set the CSV log file name. |
| `:quit` | Stop the emulator and exit the shell. |

## Output routing

`:output` decides where **all** watchpoint hits go:

| Mode | Behaviour |
| --- | --- |
| `shell` | Show watchpoint hits on the terminal (default). |
| `log` | Hide watchpoint output on the terminal and write it to the CSV file. |
| `both` | Show watchpoint hits and write them to the CSV file. |

In `log` mode nothing from a watchpoint hit reaches the screen, so the shell keeps a fixed status line at the bottom with the running total of logged events and a counter per watchpoint. Because the hit block is hidden there, the prompt and that status line stay up while the game runs, so the counter is continuously visible and updates on every hit; a hit that is only logged still stops the emulator, exactly as the native debugger does.

`:logfile <file>` sets the CSV file name; the default is `output_<timestamp>.csv` (with milliseconds, so two sessions never collide). The file is created **lazily**, on the first hit that is actually logged: until then the chosen name only exists in memory. If a user-supplied name already exists, an increasing numeric suffix is appended (for example `report_1.csv`, `report_2.csv`) so earlier logs are never overwritten. Changing `:logfile` starts a new file on the next logged hit.

## Watchpoint logging workflow

Watchpoints are created with the native debugger command `w` (see the debugger's own `help`). The wrapper only *observes* them:

```text
w 0 $574 2 W
Memwatch breakpoints enabled
 0: 00000574 - 00000575 (2)  W  CPU
:output log
[wrapper] output: log
:logfile ball.csv
[wrapper] logfile: /path/to/ball.csv
g
```

From then on, every hit of every watchpoint is appended to `ball.csv` and hidden from the terminal, with per-watchpoint counters shown in the status line. A hit looks like this in the debugger output (confirmed against FS-UAE):

```text
Memwatch 0: break at 00000574.W  W  000000FB PC=0000B8A6 CPUDW (000)
```

A watchpoint hit stops the emulator at the debugger prompt, exactly as the native debugger does. The wrapper logs the hit and leaves control with you; emulation continues only when you send `g` (or another command) yourself.

## Log file format

CSV, UTF-8, append-only. A header row is written when the file is created or empty. Records are flushed immediately.

```text
timestamp,frame,wp,address,size,access,value,pc
2026-10-10T21:14:35.165,25,0,0x00000574,W,W,0x00000080,0x0000C28C
```

| Column | Meaning |
| --- | --- |
| `timestamp` | ISO-8601 local time, without a timezone offset. |
| `frame` | Frame counter from FS-UAE's enhanced hit output (decimal); empty for the original format. |
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
- [`docs/debug-shell-output.md`](docs/debug-shell-output.md) — the exact output formats captured from real FS-UAE sessions, including the raw fixtures used by the parser tests.
- [`CHANGELOG.md`](CHANGELOG.md) — what has changed.

## Testing

Unit tests (no emulator required):

```sh
uv run python -m unittest discover -s tests
```

They cover parsing (including partial/multi-line output), command dispatch and completion, output routing and log-file naming, CSV creation/append/error handling, console input state, and child-output handling. Parser tests use real captured output in `tests/fixtures/`.

### Checks

- `uv run python -m unittest discover -s tests` — 101 tests, all passing.
- `uvx ruff check .` — clean.
- No type checker (mypy/pyright) is configured in this project.

## Known limitations

- Only output formats confirmed against FS-UAE 3.3.0 or higher are parsed. Other versions or WinUAE differ.
- Watchpoints are created with the native `w` command; the wrapper does not create them for you.
- In `log` mode watchpoint output is intentionally hidden from the terminal; use `:output both` to see it as well. The prompt stays up while the game runs there so the status line is always visible; FS-UAE does not read console input while running, so typing while it is not halted has no effect.
- Command history is kept in memory for the current session; it is not persisted across runs.
