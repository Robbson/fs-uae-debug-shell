# Architecture

How the FS-UAE Debug Wrapper is structured. For the reasoning behind these choices see [`decisions.md`](decisions.md); for the debugger output formats the parser relies on see [`fs-uae-debugger-output.md`](fs-uae-debugger-output.md).

## Overview

The wrapper launches FS-UAE as a child process on a pseudo-terminal (PTY) and owns that console for its whole lifetime.  A single-threaded event loop watches the terminal and the child PTY with `select()` and multiplexes between them:

- output read from the child is forwarded to the terminal verbatim and fed to an incremental parser that emits structured events;
- input read from the terminal is decoded by a line editor and then either dispatched as a wrapper command or forwarded to FS-UAE unchanged.

```
keyboard ─▶ Terminal / LineEditor ─▶ Application ─┬─▶ CommandDispatcher ─▶ WatchpointManager
                                                   └─▶ Session (PTY) ──────▶ fs-uae

fs-uae ──▶ Session (PTY) ─▶ Application ─┬─▶ Terminal (display)
                                          └─▶ DebuggerOutputParser ─▶ events
                                                                       ├─▶ WatchpointManager ─▶ CsvEventWriter
                                                                       └─▶ resume decision
```

## Modules

| Module | Responsibility |
| --- | --- |
| `main.py` | Entry point; calls `cli.main`. |
| `src/fs_uae_debug_wrapper/cli.py` | Argument parsing and wrapper logging setup. |
| `src/fs_uae_debug_wrapper/config.py` | `AppConfig` runtime configuration dataclass. |
| `src/fs_uae_debug_wrapper/app.py` | Orchestration: event loop, state, resume decisions, wiring. |
| `src/fs_uae_debug_wrapper/session.py` | FS-UAE process ownership over a `pexpect` PTY; `SessionState`. |
| `src/fs_uae_debug_wrapper/terminal.py` | Raw terminal input, local echo/line editing, output forwarding. |
| `src/fs_uae_debug_wrapper/parser.py` | Incremental debugger output parser and event types. |
| `src/fs_uae_debug_wrapper/commands.py` | Wrapper command parsing and dispatch. |
| `src/fs_uae_debug_wrapper/watchpoints.py` | Watchpoint id ↔ log file management. |
| `src/fs_uae_debug_wrapper/eventlog.py` | Append-only CSV event writer. |

`eventlog.py` is named to avoid shadowing the Python standard-library `logging` module (see [`decisions.md`](decisions.md)).

## Data flow

1. `Session.start` spawns FS-UAE on a PTY with child echo disabled.
2. `Application._loop` uses `select()` on the terminal fd and the child PTY fd.
3. Child output: bytes are written to the terminal, decoded as Latin-1, and passed to `DebuggerOutputParser.feed`, which returns a list of `Event`s.
4. `Application._process_events` reacts to events: it updates debugger definitions, tracks the prompt, handles watchpoint hits, and drives resume.
5. Terminal input: `LineEditor.feed` turns bytes into `"line"` and `"raw"` events with local echo.  `Application` dispatches lines starting with the wrapper prefix to `CommandDispatcher`; everything else is written to the child PTY unchanged.

## State model

`SessionState` is the high-level emulated-session state:

| State | Meaning |
| --- | --- |
| `RUNNING` | Emulation is running (debugger inactive or resumed). |
| `STOPPED` | The debugger console is at its `>` prompt. |
| `CLOSED` | The child process is gone. |

The application additionally tracks two internal flags:

- `_at_prompt` — a prompt was seen and the debugger is awaiting a command.
- `_pending_resume` — a configured, successfully logged hit is waiting for the prompt before `g` is sent.

## Debugger output parser

`parser.py` recognises the formats confirmed on FS-UAE 3.2.35 (see `fs-uae-debugger-output.md`):

- activation: the exact line `WARNING: Activated debugger`;
- watchpoints enabled: the exact line `Memwatch breakpoints enabled`;
- watchpoint definition: `<id>: <start> - <end> (<len>)  <access>  <scope>`;
- watchpoint hit: `Memwatch <id>: break at <addr>.<size>  <access>  <value> PC=<pc> <trailer>`;
- the prompt: a bare `>` at the start of a line.

The parser is incremental: it buffers partial lines across `feed()` calls and recognises the prompt without a trailing newline.

## Resume decision

Automatic resume is deliberately conservative:

1. On a `WATCHPOINT_HIT`, look up the watchpoint in `WatchpointManager`.
2. If there is no logging configuration, report the hit and do **not** resume.
3. If there is a configuration, append the hit to its CSV file.  On a write failure, report the error, leave the emulator stopped, and do not resume.
4. On success, set `_pending_resume` only if automatic resume is enabled.
5. On the `PROMPT` event, send `g` only if `_pending_resume` is set and no user input is pending in the line editor.

Unrelated stops (manual activation, breakpoints, exceptions) never set `_pending_resume`, so they remain under the user's control.

## Concurrency

The design is single-threaded and blocking-free during normal operation:

- `select()` with a 0.2 s timeout multiplexes terminal and child input.
- `SIGWINCH` is captured in a handler that only sets a flag; the resize is applied at the top of the next loop iteration.
- The terminal is put into raw mode (no canonical processing, no echo, no signals) so the wrapper can route input itself and keep `:` commands out of the emulator.  No asynchronous framework or extra threads are used.
