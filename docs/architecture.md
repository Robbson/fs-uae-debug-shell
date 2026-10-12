# Architecture

How the _Debug Shell_ is structured. For the reasoning behind these choices see [`decisions.md`](decisions.md); for the debugger output formats the parser relies on see [`debug-shell-output.md`](debug-shell-output.md).

## Overview

The shell launches FS-UAE as a child process on a pseudo-terminal (PTY) and owns that console for its whole lifetime. The interactive input line is provided by `prompt_toolkit`; one `asyncio` event loop multiplexes that prompt with reading the child PTY:

- output read from the child is routed to the console and/or the log file according to the current output mode, and fed to an incremental parser that emits structured events;
- lines read from the prompt are either dispatched as a shell command or forwarded to FS-UAE unchanged.

```
 keyboard ─▶ Console (prompt_toolkit) ─▶ Application ─┬─▶ CommandDispatcher ─▶ OutputRouter
                                                      └─▶ Session (PTY) ──────▶ fs-uae

 fs-uae ──▶ Session (PTY) ─▶ Application ─┬─▶ Console (patch_stdout + status line)
                                          └─▶ DebuggerOutputParser ─▶ events
                                                                       └─▶ FrameValueSelector ─▶ FrameAggregator ─▶ OutputRouter ─▶ CsvEventWriter
```

## Modules

| Module | Responsibility |
| --- | --- |
| `main.py` | Entry point; calls `cli.main`. |
| `src/fs_uae_debug_shell/cli.py` | Argument parsing and wrapper logging setup. |
| `src/fs_uae_debug_shell/config.py` | `AppConfig` runtime configuration dataclass. |
| `src/fs_uae_debug_shell/app.py` | Orchestration: event loop, state, wiring. |
| `src/fs_uae_debug_shell/session.py` | FS-UAE process ownership over a `pexpect` PTY; `SessionState`; debugger activation by `SIGUSR1`. |
| `src/fs_uae_debug_shell/terminal.py` | Interactive prompt via `prompt_toolkit`: line editing/history, completion (`WrapperCompleter`), `patch_stdout` output and the status line (`Console`). |
| `src/fs_uae_debug_shell/parser.py` | Incremental debugger output parser and event types. |
| `src/fs_uae_debug_shell/frames.py` | Per-frame selection of watchpoint hits (`FrameValueMode`, `FrameValueSelector`). |
| `src/fs_uae_debug_shell/aggregate.py` | Per-frame condensation of hits into one row (`FrameAggregator`, `AggregatedFrame`). |
| `src/fs_uae_debug_shell/dump.py` | Whether the debugger's CPU register dump is shown on the terminal (`RegisterDump`). |
| `src/fs_uae_debug_shell/scenarios.py` | `config.yaml` scenario model, validation loader, and the runtime alias/number registry (`ScenarioCatalog`, `WatchpointRegistry`). |
| `src/fs_uae_debug_shell/commands.py` | Shell command parsing, dispatch, and the completion tables. |
| `src/fs_uae_debug_shell/output.py` | Output routing: `OutputMode`, log-file naming, lazy CSV creation, per-watchpoint counters. |
| `src/fs_uae_debug_shell/eventlog.py` | Append-only CSV event writer for the per-hit and per-frame schemas. |

`eventlog.py` is named to avoid shadowing the Python standard-library `logging` module (see [`decisions.md`](decisions.md)).

## Data flow

1. `Session.start` spawns FS-UAE on a PTY with child echo disabled.
2. `Application._run_async` registers the child PTY fd with `loop.add_reader` and enters `Console.patched_stdout()`.
3. Child output: the reader callback decodes the text and passes it to `DebuggerOutputParser.feed_pieces`, which returns `Piece`s in order (the exact text plus any structured `Event`). Everything produced by one read is written to the terminal in a single `Console.write` call.
4. `Application._handle_piece` routes each piece. Pieces marked as part of a CPU register dump are dropped when `:showdump` is `off`. Watchpoint hits pass through `FrameValueSelector`, which keeps the chosen value per frame and watchpoint (`:framevalues`); with `:frameagg` on and a frame counter present, the selected hits then pass through `FrameAggregator`, which condenses each frame into one row. The resulting hit or frame is shown and/or logged according to `OutputRouter`. `_process_events` updates debugger definitions and tracks the prompt.
5. Input: `Console.prompt_async` returns one edited line. `Application` dispatches lines starting with the shell prefix to `CommandDispatcher`; everything else is written to the child PTY unchanged.

The interactive prompt is only raised while the debugger is idle at its own `>` prompt (see below) — except in `log` mode, where it stays up for the status line — so the bulk of debugger output is written directly rather than repainted above a prompt.

## Startup debugger activation

With `--startdebug`, `cli.parse_args` prefixes the FS-UAE arguments with `--console_debugger=1 --debugger_signal=1 --stdout` (unless the user already supplied them) and sets `AppConfig.start_debug` with an optional `start_debug_delay_ms`. The forked FS-UAE build installs a `SIGUSR1` handler and prints `debugger_signal: sending SIGUSR1 will activate the debugger`; the parser recognises that marker as a `DEBUGGER_SIGNAL_READY` event, and `Application._activate_debugger` sends `SIGUSR1` exactly once through `Session.activate_debugger`. The marker gates the signal because an earlier `SIGUSR1` would use the default action and kill the process, so a non-zero delay is scheduled from the marker with `loop.call_later` (cancelled at shutdown or on child exit) rather than from process start. Without the flag the marker is ignored and activation stays manual (F12+D), preserving the transparent default.

## State model

`SessionState` is the high-level emulated-session state:

| State | Meaning |
| --- | --- |
| `RUNNING` | Emulation is running (debugger inactive or resumed). |
| `STOPPED` | The debugger console is at its `>` prompt. |
| `CLOSED` | The child process is gone. |

The application additionally tracks one internal flag and one internal event:

- `_suppress_block` — a watchpoint hit is being hidden (set in `log` mode until the next prompt).
- `_prompt_ready` — an `asyncio.Event` set when the debugger prints its `>` prompt and cleared when the wrapper forwards a command; it gates when the interactive prompt is shown.

## Debugger output parser

`parser.py` recognises the formats confirmed on FS-UAE (see `debug-shell-output.md`):

- activation: the exact line `WARNING: Activated debugger`;
- watchpoints enabled: the exact line `Memwatch breakpoints enabled`;
- watchpoint definition: `<id>: <start> - <end> (<len>)  <access>  <scope>`;
- watchpoint hit: `Memwatch <id>: break at <addr>.<size>  <access>  <value> PC=<pc> <trailer>`;
- the prompt: a bare `>` at the start of a line.

The parser is incremental: it buffers partial lines across `feed_pieces()` calls and recognises the prompt without a trailing newline. `feed()` remains as a convenience that returns only the structured events. A chunk is walked with a cursor into a single buffer and only the unfinished tail is copied at the end, so parsing a large chunk is one pass rather than a fresh slice per line.

## Output routing and logging

`OutputRouter` owns the global log settings:

- `OutputMode` is `shell`, `log` or `both` (default `shell`);
- `display_enabled` / `log_enabled` say whether hits are shown and/or written;
- the log file name is either user-supplied (`:logfile`) or the default `output_<timestamp>.csv`, and the file is created lazily on the first logged hit;
- a user-supplied name that already exists gets an increasing numeric suffix;
- per-watchpoint counters exist only for logged hits.

`Application._on_hit` records a single hit and `_on_frame` records a condensed frame; both refresh the status line when logging. On a write failure the error is reported and the emulator is simply left stopped. Emulation is **never** resumed automatically; the user sends `g` (or any other command) themselves.

`CommandDispatcher` provides `:output`, `:logfile`, `:framevalues`, `:frameagg`, `:showdump`, and `:sci` to change those settings, plus `:help`, `:status`, and `:quit`.

## Frame value selection

The enhanced hit line carries a leading video-frame counter. A single frame can contain several writes to the same watchpoint because the game loop runs more often than frames are rendered, and only one of those values is normally shown on screen. `FrameValueSelector` (`frames.py`) groups hits by `(frame, watchpoint)` and keeps the `first`, `last`, or `all` of them according to `FrameValueMode`, chosen with `:framevalues` (default `first`):

- `first` emits the first occurrence of each watchpoint in a frame and drops the rest;
- `last` buffers a frame and emits one hit per watchpoint when the frame number changes;
- `all` emits every hit.

A hit without a frame counter (classic output) is always emitted and ignores the mode. The selector is flushed when a frame ends, when any other structured event arrives (for example the debugger prompt), and at shutdown, so a buffered frame is never lost.

## Frame aggregation

`FrameAggregator` (`aggregate.py`) sits after the value selector and condenses the selected hits of a video frame into one `AggregatedFrame` that keeps only the watchpoint ids and their values. It buffers hits by frame and emits a row when the frame number changes; `Application` flushes it whenever another structured event arrives and at shutdown, in step with the value selector. `format_frame_line` renders the row as `<frame> <wp>:<value> <wp>:<value> ...`; every watchpoint column is printed, so a watchpoint that did not write keeps its padding as blanks.

The columns are the watchpoint ids the wrapper knows about: ids from parsed `Memwatch` definitions (seeded through `_process_events`) plus ids seen in hits (added in `Application._emit_hit`). A watchpoint first seen after the log file was created cannot fit the frozen header and is reported as a logging error.

`:frameagg` (default `on`) is exposed by `CommandDispatcher` and only applies to hits that carry a frame counter; classic hits and a disabled aggregator emit the original hit piece unchanged. The classic per-hit CSV schema and the wide per-frame schema are chosen by which record method the application calls (`OutputRouter.record` versus `record_frame`); `CsvEventWriter` carries the matching header and rejects records of the other shape.

## CPU register dump filtering

The debugger prints a CPU register dump whenever it stops (manual activation or a watchpoint break). The parser brackets the block between the `-- stub -- activate_console` marker and the `Next PC:` line and marks every piece in between with `Piece.in_dump`, so a split read keeps the boundary in the parser's state (and the debugger prompt clears it). `Application._handle_piece` drops those pieces when `RegisterDump.enabled` is false. The introducing `WARNING: Activated debugger` / `Memwatch ...` lines are not part of the block and stay visible, and the `r` command's dump has no stub marker so it is never matched. The setting is terminal-only and does not affect logging; `:showdump on|off` (default `on`) toggles it.

## Watchpoint scenarios

Named watchpoints live in `config.yaml`, loaded by `cli` into `AppConfig.scenarios`. `scenarios.py` owns the whole concern:

- `ScenarioCatalog` is the parsed, validated configuration: ordered scenarios, each a list of `ScenarioEntry` with defaults already applied;
- `WatchpointRegistry` holds the runtime state: the next free watchpoint number, the active scenario to `(number, entry)` assignments, and the number to alias map.

`CommandDispatcher._cmd_sci` adds or removes scenarios, asks the registry to assign or free numbers, and returns the generated `w` commands in `CommandResult.commands` (an add emits `w <num> <address> <length> <flags>...`, a remove emits `w <num>`); `Application._handle_line` sends them to the child and, like a forwarded command, drops the interactive prompt until the debugger prints `>` again. `:sci` with no argument lists the active scenarios, and `*` expands to every configured scenario (or every active one for `rm`).

Aliases replace numbers in the wrapper's own output only: `Application._emit_aggregate` passes `WatchpointRegistry.aliases()` to `format_frame_line`, `OutputRouter` holds the same provider for the CSV writer (the per-hit `wp` cell and the wide per-frame header), and `_status_text`/`_toolbar_text` label counters and definitions through it. Verbatim debugger lines are never rewritten. `WatchpointRegistry` exposes the configured scenario names to `WrapperCompleter` so `:sci add`/`rm` complete scenario names.

The configuration is validated by `parse_scenarios`, which raises `ConfigError` with a located message; `cli.parse_args` turns that into a startup abort. The `--config` path must exist if given; a missing default `./config.yaml` simply leaves the feature inert.

## Interactive input

`Console` wraps a `prompt_toolkit` `PromptSession`. `WrapperCompleter` completes shell command names and their arguments (fixed choices for `:output`, filesystem paths for `:logfile`, configured scenario names for `:sci add`/`rm`). The shell renders its own `> ` prompt through `prompt_toolkit` and hides the debugger's bare `>` so the cursor sits after the prompt rather than on top of it. In `log` mode, `Application._input_loop` passes a `bottom_toolbar` callback that renders the per-watchpoint counters as a fixed status line; `Console.refresh()` invalidates the prompt so the counters update as hits arrive.

The prompt follows the debugger's own input semantics in `shell` and `both` mode: it is raised only while the debugger is idle at its `>` prompt. `_input_loop` waits on `_prompt_ready`; a `PROMPT` event sets it, and forwarding a command clears it until the debugger prints `>` again. While emulation runs, and while a command's output is still arriving, no `prompt_toolkit` application is running, so `patch_stdout` writes child output straight to the terminal instead of erasing and repainting a prompt for every output batch.

`log` mode is the exception. Its hit block is hidden, so the status line is the only feedback and the prompt (with its toolbar) stays raised while emulation runs, so the per-watchpoint counter never disappears on resume; `_prompt_is_persistent` expresses this. Nothing is repainted in that mode because the hit block is not written, and the counter is updated through `Console.refresh()` when a hit is logged.

## Concurrency

The design uses one `asyncio` event loop:

- `loop.add_reader` reads the child PTY as output arrives; `Console.prompt_async()` reads the input line. Both run on the same loop, so no threads are needed.
- `patch_stdout(raw=True)` renders child output above the active prompt, so asynchronous debugger output cannot corrupt the line being typed. Because the prompt is only active at the debugger's `>` prompt (except in `log` mode, where the hidden hit blocks leave nothing to repaint), most output bypasses this path and is written directly.
- Each PTY read is parsed into pieces and written in a single `Console.write` call, so a multi-line dump is one write rather than one per line.
- The child PTY is resized to the current terminal size before each prompt (`prompt_toolkit` owns the `SIGWINCH` handler while the prompt is active and repaints its own line).
- `pexpect` keeps ownership of the child PTY (echo disabled); only `prompt_toolkit` reads stdin, so there is no competing read of the terminal.
