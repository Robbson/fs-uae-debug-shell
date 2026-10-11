# Architecture

How the _Debug Shell_ is structured. For the reasoning behind these choices see [`decisions.md`](decisions.md); for the debugger output formats the parser relies on see [`fs-uae-debugger-output.md`](fs-uae-debugger-output.md).

## Overview

The wrapper launches FS-UAE as a child process on a pseudo-terminal (PTY) and owns that console for its whole lifetime. The interactive input line is provided by `prompt_toolkit`; one `asyncio` event loop multiplexes that prompt with reading the child PTY:

- output read from the child is written to the console and fed to an incremental parser that emits structured events;
- lines read from the prompt are either dispatched as a wrapper command or forwarded to FS-UAE unchanged.

```
 keyboard ─▶ Console (prompt_toolkit) ─▶ Application ─┬─▶ CommandDispatcher ─▶ WatchpointManager
                                                      └─▶ Session (PTY) ──────▶ fs-uae

 fs-uae ──▶ Session (PTY) ─▶ Application ─┬─▶ Console (patch_stdout)
                                          └─▶ DebuggerOutputParser ─▶ events
                                                                       └─▶ WatchpointManager ─▶ CsvEventWriter
```

## Modules

| Module | Responsibility |
| --- | --- |
| `main.py` | Entry point; calls `cli.main`. |
| `src/fs_uae_debug_wrapper/cli.py` | Argument parsing and wrapper logging setup. |
| `src/fs_uae_debug_wrapper/config.py` | `AppConfig` runtime configuration dataclass. |
| `src/fs_uae_debug_wrapper/app.py` | Orchestration: event loop, state, wiring. |
| `src/fs_uae_debug_wrapper/session.py` | FS-UAE process ownership over a `pexpect` PTY; `SessionState`. |
| `src/fs_uae_debug_wrapper/terminal.py` | Interactive prompt via `prompt_toolkit`: line editing/history, `patch_stdout` output (`Console`). |
| `src/fs_uae_debug_wrapper/parser.py` | Incremental debugger output parser and event types. |
| `src/fs_uae_debug_wrapper/commands.py` | Wrapper command parsing and dispatch. |
| `src/fs_uae_debug_wrapper/watchpoints.py` | Watchpoint ↔ log file management. |
| `src/fs_uae_debug_wrapper/eventlog.py` | Append-only CSV event writer. |

`eventlog.py` is named to avoid shadowing the Python standard-library `logging` module (see [`decisions.md`](decisions.md)).

## Data flow

1. `Session.start` spawns FS-UAE on a PTY with child echo disabled.
2. `Application._run_async` registers the child PTY fd with `loop.add_reader` and enters `Console.patched_stdout()`.
3. Child output: the reader callback decodes the text and passes it to `DebuggerOutputParser.feed_pieces`, which returns `Piece`s in order (the exact text plus any structured `Event`).
4. `Application._handle_piece` writes each piece unchanged and routes any event to `_process_events`, which updates debugger definitions, tracks the prompt, and logs watchpoint hits.
5. Input: `Console.prompt_async` returns one edited line. `Application` dispatches lines starting with the wrapper prefix to `CommandDispatcher`; everything else is written to the child PTY unchanged.

## State model

`SessionState` is the high-level emulated-session state:

| State | Meaning |
| --- | --- |
| `RUNNING` | Emulation is running (debugger inactive or resumed). |
| `STOPPED` | The debugger console is at its `>` prompt. |
| `CLOSED` | The child process is gone. |

The application additionally tracks one internal flag:

- `_at_prompt` — a prompt was seen and the debugger is awaiting a command.

## Debugger output parser

`parser.py` recognises the formats confirmed on FS-UAE 3.2.35 (see `fs-uae-debugger-output.md`):

- activation: the exact line `WARNING: Activated debugger`;
- watchpoints enabled: the exact line `Memwatch breakpoints enabled`;
- watchpoint definition: `<id>: <start> - <end> (<len>)  <access>  <scope>`;
- watchpoint hit: `Memwatch <id>: break at <addr>.<size>  <access>  <value> PC=<pc> <trailer>`;
- the prompt: a bare `>` at the start of a line.

The parser is incremental: it buffers partial lines across `feed_pieces()` calls and recognises the prompt without a trailing newline. `feed()` remains as a convenience that returns only the structured events.

## Watchpoint logging

Output is displayed piece by piece exactly as it arrives, so nothing is rewritten or hidden. When a `WATCHPOINT_HIT` event is parsed, `Application._on_hit` looks the watchpoint up in `WatchpointManager`:

1. If the watchpoint has no logging configuration, the wrapper reports the hit and does nothing else.
2. If it is configured, the hit is appended to its CSV file. On a write failure the error is reported and the emulator is simply left stopped.
3. Emulation is **never** resumed automatically; the user sends `g` (or any other command) themselves.

`CommandDispatcher` provides `:logwatch <id> <file>` and `:logoff <id>` to add and remove those configurations, and `WatchpointManager` owns the watchpoint ↔ log file mapping.

## Concurrency

The design uses one `asyncio` event loop:

- `loop.add_reader` reads the child PTY as output arrives; `Console.prompt_async()` reads the input line. Both run on the same loop, so no threads are needed.
- `patch_stdout(raw=True)` renders child output above the active prompt, so asynchronous debugger output cannot corrupt the line being typed.
- The child PTY is resized to the current terminal size before each prompt (`prompt_toolkit` owns the `SIGWINCH` handler while the prompt is active and repaints its own line).
- `pexpect` keeps ownership of the child PTY (echo disabled); only `prompt_toolkit` reads stdin, so there is no competing read of the terminal.
