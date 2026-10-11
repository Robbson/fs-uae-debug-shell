# Architecture

How the FS-UAE Debug Wrapper is structured. For the reasoning behind these choices see [`decisions.md`](decisions.md); for the debugger output formats the parser relies on see [`fs-uae-debugger-output.md`](fs-uae-debugger-output.md).

## Overview

The wrapper launches FS-UAE as a child process on a pseudo-terminal (PTY) and owns that console for its whole lifetime.  The interactive input line is provided by `prompt_toolkit`; one `asyncio` event loop multiplexes that prompt with reading the child PTY:

- output read from the child is written to the console and fed to an incremental parser that emits structured events;
- lines read from the prompt are either dispatched as a wrapper command or forwarded to FS-UAE unchanged.

```
 keyboard ─▶ Console (prompt_toolkit) ─▶ Application ─┬─▶ CommandDispatcher ─▶ WatchpointManager
                                                     └─▶ Session (PTY) ──────▶ fs-uae

 fs-uae ──▶ Session (PTY) ─▶ Application ─┬─▶ Console (patch_stdout)
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
| `src/fs_uae_debug_wrapper/terminal.py` | Interactive prompt via `prompt_toolkit`: line editing/history, `patch_stdout` output (`Console`). |
| `src/fs_uae_debug_wrapper/parser.py` | Incremental debugger output parser and event types. |
| `src/fs_uae_debug_wrapper/commands.py` | Wrapper command parsing and dispatch. |
| `src/fs_uae_debug_wrapper/watchpoints.py` | Watch definitions, change filters, generated log paths, watchpoint ↔ log file management. |
| `src/fs_uae_debug_wrapper/eventlog.py` | Append-only CSV event writer. |

`eventlog.py` is named to avoid shadowing the Python standard-library `logging` module (see [`decisions.md`](decisions.md)).

## Data flow

1. `Session.start` spawns FS-UAE on a PTY with child echo disabled.
2. `Application._run_async` registers the child PTY fd with `loop.add_reader` and enters `Console.patched_stdout()`.
3. Child output: the reader callback decodes the text and passes it to `DebuggerOutputParser.feed_pieces`, which returns `Piece`s in order (the exact text plus any structured `Event`).
4. `Application._handle_piece` decides what to show and routes the event to `_process_events`, which updates debugger definitions, tracks the prompt, handles watchpoint hits, and drives resume.
5. Input: `Console.prompt_async` returns one edited line.  `Application` dispatches lines starting with the wrapper prefix to `CommandDispatcher`; everything else is written to the child PTY unchanged.

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

Whether the user has already typed something is delegated to `Console.input_pending()`, which reads the current `prompt_toolkit` buffer; automatic resume is skipped when it is non-empty.

## Debugger output parser

`parser.py` recognises the formats confirmed on FS-UAE 3.2.35 (see `fs-uae-debugger-output.md`):

- activation: the exact line `WARNING: Activated debugger`;
- watchpoints enabled: the exact line `Memwatch breakpoints enabled`;
- watchpoint definition: `<id>: <start> - <end> (<len>)  <access>  <scope>`;
- watchpoint hit: `Memwatch <id>: break at <addr>.<size>  <access>  <value> PC=<pc> <trailer>`;
- the prompt: a bare `>` at the start of a line.

The parser is incremental: it buffers partial lines across `feed_pieces()` calls and recognises the prompt without a trailing newline.  `feed()` remains as a convenience that returns only the structured events.

## Output filtering

Output is displayed piece by piece as it arrives, so nothing is rewritten.  When a hit of a configured watchpoint is logged *and* will be automatically resumed, `Application` suppresses the following pieces (the register dump, disassembly, `Next PC`, and the prompt) until the prompt ends the block; the `Memwatch ...` hit line itself is always shown.  `--show-watchpoint-dump` turns this suppression off.  Unconfigured hits, manual activations, and `:auto off` are shown in full.  The per-hit wrapper summary line is likewise only printed with `--show-watchpoint-dump`.

## Watch change filter

`:wwcl` creates a watch with a change filter.  `WatchpointManager` keeps the last value seen for each filtered watch; a hit whose value equals the stored value is a *duplicate*: it is not written to the CSV and its line is not displayed, but emulation is still resumed.  Only watches created by `:wwcl` are filtered; plain `:logwatch` watches log every hit.  `CommandDispatcher` translates a `:wwcl` request into native `w <id> $<addr> <len> W` commands (returned as `CommandResult.forward`, which `Application` sends to the session) and enables logging to a generated `<name1>_<name2>_NNN.csv` file.

## Resume decision

Automatic resume is deliberately conservative:

1. On a `WATCHPOINT_HIT`, look up the watchpoint in `WatchpointManager`.
2. If there is no logging configuration, report the hit and do **not** resume.
3. If there is a configuration, append the hit to its CSV file.  On a write failure, report the error, leave the emulator stopped, and do not resume.
4. On success, set `_pending_resume` only if automatic resume is enabled.
5. On the `PROMPT` event, send `g` only if `_pending_resume` is set and no user input is pending in the line editor.

Unrelated stops (manual activation, breakpoints, exceptions) never set `_pending_resume`, so they remain under the user's control.

## Concurrency

The design uses one `asyncio` event loop:

- `loop.add_reader` reads the child PTY as output arrives; `Console.prompt_async()` reads the input line.  Both run on the same loop, so no threads are needed.
- `patch_stdout(raw=True)` renders child output above the active prompt, so asynchronous debugger output cannot corrupt the line being typed.
- The child PTY is resized to the current terminal size before each prompt (`prompt_toolkit` owns the `SIGWINCH` handler while the prompt is active and repaints its own line).
- `pexpect` keeps ownership of the child PTY (echo disabled); only `prompt_toolkit` reads stdin, so there is no competing read of the terminal.
