# Decisions

Why the _Debug Shell_ is built the way it is.  Each record captures the context, the decision, and its consequences.  Keep the log describing the decisions that apply to the current code, free of superseded or abandoned experiments.  For the resulting structure see [`architecture.md`](architecture.md).

## ADR-0001: The wrapper launches FS-UAE; it does not attach

**Context.** FS-UAE binds its console debugger to the terminal it was started from and offers no way to attach to a running instance afterwards.

**Decision.** The wrapper launches FS-UAE as a child process and owns its console for the whole session.  Attaching to an externally started FS-UAE is unsupported and documented as such.

**Consequences.** The wrapper can rely on owning the PTY.  Users must always start FS-UAE through the wrapper.  When the wrapper's terminal goes away it terminates the child so no emulator is left running.

## ADR-0002: Reserved, configurable command prefix

**Context.** Automation commands must not collide with the native debugger's command namespace.

**Decision.** Wrapper commands use a reserved prefix, configurable via `--prefix`, defaulting to `:`.  Lines starting with the prefix are intercepted; every other line is forwarded unchanged.

**Consequences.** The wrapper command namespace is disjoint from FS-UAE's.  A single-character prefix keeps typing short; changing it is possible if `:` ever clashes.

## ADR-0003: Parse only confirmed FS-UAE 3.2.35 output

**Context.** FS-UAE and WinUAE output formats are not guaranteed to match, and guessed formats would silently corrupt logs.

**Decision.** Implement parsing only for formats captured from real FS-UAE sessions (kept in `tests/fixtures/` and documented in `debug-shell-output.md`).  Unknown lines are passed through untouched and never turned into fabricated data.

**Consequences.** The parser is small and trustworthy, but version-specific; supporting another version means capturing and verifying its output first.

## ADR-0004: Child echo disabled, line input provided by `prompt_toolkit`

**Context.** In a plain FS-UAE session the PTY has kernel echo enabled, so typed commands are echoed back (`>r`, `>g`, ...).  If the wrapper also echoed, input would appear twice, and intercepted `:` commands would still reach the emulator's echo.  The debugger itself has no readline-style editing, and asynchronous debugger output must not corrupt the line being typed.

**Decision.** Spawn FS-UAE with `echo=False` and provide the input line with `prompt_toolkit`'s `PromptSession`, driven by an `asyncio` loop.  The child PTY is read with `loop.add_reader` and its output is rendered above the prompt with `patch_stdout(raw=True)`; `Console` in `terminal.py` wraps this.  `pexpect` keeps ownership of the child PTY; only `prompt_toolkit` reads stdin.

**Consequences.** Input is shown exactly once and `:` commands never reach the emulator.  Cursor movement, Home/End, Backspace/Delete, and Up/Down history come from `prompt_toolkit`'s default key bindings; history is in-memory for the session only.  The wrapper depends on `prompt_toolkit` and uses `asyncio` for its input loop.  Only `prompt_toolkit` reads stdin, so there is no competing read of the terminal.

## ADR-0005: Append-only CSV with a fixed schema and per-record flush

**Context.** Logging must survive interruption and be trivially inspectable, and it must not fabricate fields the debugger did not print.

**Decision.** Write UTF-8 CSV in append mode.  Write the header only when the file is created or empty, flush after every record, and record exactly the fields present in the `Memwatch ...` line plus an ISO-8601 timestamp.

**Consequences.** Files are robust and easy to diff or load.  The schema is intentionally small and specific rather than a generic logging framework.

## ADR-0006: `eventlog.py` rather than `logging.py`

**Context.** The wrapper's own diagnostics use Python's standard `logging` module; a local module named `logging.py` inside the package would shadow it confusingly.

**Decision.** Name the CSV writer module `eventlog.py`.

**Consequences.** Import resolution stays unambiguous and readers are not misled into expecting standard-library logging behaviour.

## ADR-0007: One global output destination for all watchpoints

**Context.** The first design bound each watchpoint id to its own log file, which meant repeatedly configuring logging per watchpoint and having no way to see or hide the combined stream at a glance.

**Decision.** Route every watchpoint hit through a single global `OutputMode`: `shell` (screen only, the default), `log` (file only), or `both`.  The `:output` command selects the mode.  In `log` mode the watchpoint hit output — the `Memwatch ...` line and its following dump block, up to the prompt — is hidden on the terminal and only written to the file.

**Consequences.** Logging is configured once and applies to every watchpoint.  `log` mode deliberately diverges from the transparent default, so it is opt-in and reported through the status line (see ADR-0009); `shell`/`both` keep the terminal fully transparent.

## ADR-0008: Lazy log-file creation and collision-free default names

**Context.** Creating a file when logging is merely *selected* would litter the filesystem and make the chosen name visible on disk before any data exists.  Reusing a name would silently append to an earlier log.

**Decision.** Keep the chosen log-file name in memory and create the file only on the first hit that is actually written.  The default name embeds a millisecond timestamp (`output_<timestamp>.csv`), so defaults never collide.  A user-supplied name that already exists gets an increasing numeric suffix (`report_1.csv`, `report_2.csv`).  `:logfile` discards the current file and counters, so the next logged hit starts a fresh file.

**Consequences.** No empty files are created and earlier logs are never overwritten.  Because creation is deferred, a bad path or permission error surfaces on the first logged hit and is reported there rather than at `:logfile` time.

## ADR-0009: Tab completion and a fixed-position counter line

**Context.** Shell commands have fixed choices and file arguments that are easy to mistype, and `log` mode hides all watchpoint output, leaving no feedback that logging works.

**Decision.** Add a `prompt_toolkit` `Completer` (`WrapperCompleter`) that completes command names and their arguments on lines that start with the shell prefix: fixed choices for `:output`, filesystem paths for `:logfile`.  In `log` mode, render a `bottom_toolbar` status line with the running total and a counter per watchpoint, refreshed by invalidating the prompt when a hit is logged.

**Consequences.** Commands are discoverable and less error-prone, and `log` mode still gives visible per-watchpoint feedback.  Completion only engages after the shell prefix, so native debugger input is untouched.  The counter lives at a fixed screen position rather than scrolling with output.
