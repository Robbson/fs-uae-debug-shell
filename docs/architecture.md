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
                                                                       └─▶ OutputRouter ─▶ CsvEventWriter
```

## Modules

| Module | Responsibility |
| --- | --- |
| `main.py` | Entry point; calls `cli.main`. |
| `src/fs_uae_debug_shell/cli.py` | Argument parsing and wrapper logging setup. |
| `src/fs_uae_debug_shell/config.py` | `AppConfig` runtime configuration dataclass. |
| `src/fs_uae_debug_shell/app.py` | Orchestration: event loop, state, wiring. |
| `src/fs_uae_debug_shell/session.py` | FS-UAE process ownership over a `pexpect` PTY; `SessionState`. |
| `src/fs_uae_debug_shell/terminal.py` | Interactive prompt via `prompt_toolkit`: line editing/history, completion (`WrapperCompleter`), `patch_stdout` output and the status line (`Console`). |
| `src/fs_uae_debug_shell/parser.py` | Incremental debugger output parser and event types. |
| `src/fs_uae_debug_shell/commands.py` | Shell command parsing, dispatch, and the completion tables. |
| `src/fs_uae_debug_shell/output.py` | Output routing: `OutputMode`, log-file naming, lazy CSV creation, per-watchpoint counters. |
| `src/fs_uae_debug_shell/eventlog.py` | Append-only CSV event writer. |

`eventlog.py` is named to avoid shadowing the Python standard-library `logging` module (see [`decisions.md`](decisions.md)).

## Data flow

1. `Session.start` spawns FS-UAE on a PTY with child echo disabled.
2. `Application._run_async` registers the child PTY fd with `loop.add_reader` and enters `Console.patched_stdout()`.
3. Child output: the reader callback decodes the text and passes it to `DebuggerOutputParser.feed_pieces`, which returns `Piece`s in order (the exact text plus any structured `Event`).
4. `Application._handle_piece` routes each piece. Watchpoint hit output is shown and/or hidden according to `OutputRouter.display_enabled`; every hit is passed to `_process_events`, which updates debugger definitions, tracks the prompt, and records the hit.
5. Input: `Console.prompt_async` returns one edited line. `Application` dispatches lines starting with the shell prefix to `CommandDispatcher`; everything else is written to the child PTY unchanged.

## State model

`SessionState` is the high-level emulated-session state:

| State | Meaning |
| --- | --- |
| `RUNNING` | Emulation is running (debugger inactive or resumed). |
| `STOPPED` | The debugger console is at its `>` prompt. |
| `CLOSED` | The child process is gone. |

The application additionally tracks one internal flag:

- `_suppress_block` — a watchpoint hit is being hidden (set in `log` mode until the next prompt).

## Debugger output parser

`parser.py` recognises the formats confirmed on FS-UAE (see `debug-shell-output.md`):

- activation: the exact line `WARNING: Activated debugger`;
- watchpoints enabled: the exact line `Memwatch breakpoints enabled`;
- watchpoint definition: `<id>: <start> - <end> (<len>)  <access>  <scope>`;
- watchpoint hit: `Memwatch <id>: break at <addr>.<size>  <access>  <value> PC=<pc> <trailer>`;
- the prompt: a bare `>` at the start of a line.

The parser is incremental: it buffers partial lines across `feed_pieces()` calls and recognises the prompt without a trailing newline. `feed()` remains as a convenience that returns only the structured events.

## Output routing and logging

`OutputRouter` owns the global log settings:

- `OutputMode` is `shell`, `log` or `both` (default `shell`);
- `display_enabled` / `log_enabled` say whether hits are shown and/or written;
- the log file name is either user-supplied (`:logfile`) or the default `output_<timestamp>.csv`, and the file is created lazily on the first logged hit;
- a user-supplied name that already exists gets an increasing numeric suffix;
- per-watchpoint counters exist only for logged hits.

`Application._on_hit` records the hit and, when logging, refreshes the status line. On a write failure the error is reported and the emulator is simply left stopped. Emulation is **never** resumed automatically; the user sends `g` (or any other command) themselves.

`CommandDispatcher` provides `:output` and `:logfile` to change those settings, plus `:help`, `:status`, and `:quit`.

## Interactive input

`Console` wraps a `prompt_toolkit` `PromptSession`. `WrapperCompleter` completes shell command names and their arguments (fixed choices for `:output`, filesystem paths for `:logfile`). The shell renders its own `> ` prompt through `prompt_toolkit` and hides the debugger's bare `>` so the cursor sits after the prompt rather than on top of it. In `log` mode, `Application._input_loop` passes a `bottom_toolbar` callback that renders the per-watchpoint counters as a fixed status line; `Console.refresh()` invalidates the prompt so the counters update as hits arrive.

## Concurrency

The design uses one `asyncio` event loop:

- `loop.add_reader` reads the child PTY as output arrives; `Console.prompt_async()` reads the input line. Both run on the same loop, so no threads are needed.
- `patch_stdout(raw=True)` renders child output above the active prompt, so asynchronous debugger output cannot corrupt the line being typed.
- The child PTY is resized to the current terminal size before each prompt (`prompt_toolkit` owns the `SIGWINCH` handler while the prompt is active and repaints its own line).
- `pexpect` keeps ownership of the child PTY (echo disabled); only `prompt_toolkit` reads stdin, so there is no competing read of the terminal.
