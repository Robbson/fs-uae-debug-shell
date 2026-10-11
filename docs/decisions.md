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

**Decision.** Implement parsing only for formats captured from real FS-UAE 3.2.35 sessions (kept in `tests/fixtures/` and documented in `fs-uae-debugger-output.md`).  Unknown lines are passed through untouched and never turned into fabricated data.

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
