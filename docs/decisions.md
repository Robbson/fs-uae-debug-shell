# Decisions

Why the FS-UAE Debug Wrapper is built the way it is.  Each record captures the context, the decision, and its consequences.  Add a new record for any non-obvious technical decision; do not rewrite old ones to hide a reversal — supersede them instead.  For the resulting structure see [`architecture.md`](architecture.md).

## ADR-0001: The wrapper launches FS-UAE; it does not attach

**Context.** FS-UAE binds its console debugger to the terminal it was started from and offers no way to attach to a running instance afterwards.

**Decision.** The wrapper launches FS-UAE as a child process and owns its console for the whole session.  Attaching to an externally started FS-UAE is unsupported and documented as such.

**Consequences.** The wrapper can rely on owning the PTY.  Users must always start FS-UAE through the wrapper.  When the wrapper's terminal goes away it terminates the child so no emulator is left running.

## ADR-0002: Reserved, configurable command prefix

**Context.** Automation commands must not collide with the native debugger's command namespace.

**Decision.** Wrapper commands use a reserved prefix, configurable via `--prefix`, defaulting to `:`.  Lines starting with the prefix are intercepted; every other line is forwarded unchanged.

**Consequences.** The wrapper command namespace is disjoint from FS-UAE's.  A single-character prefix keeps typing short; changing it is possible if `:` ever clashes.

## ADR-0003: Single-threaded `select()` loop instead of an async framework

**Context.** User input and debugger output must be handled concurrently, but the workload is small and `pexpect`/POSIX terminals are synchronous.

**Decision.** Use one thread with `select()` over the terminal fd and the child PTY fd, with a 0.2 s timeout.  Do not introduce `asyncio` or extra concurrency libraries.

**Consequences.** The control flow stays simple and debuggable, and there are no locks or thread-safety concerns.  `SIGWINCH` is reduced to a flag that is applied between loop iterations.

## ADR-0004: Disable child echo and do local line editing

**Context.** In a plain FS-UAE session the PTY has kernel echo enabled, so typed commands are echoed back.  If the wrapper also echoed, input would appear twice, and intercepted `:` commands would still reach the emulator's echo.

**Decision.** Spawn FS-UAE with `echo=False` and put the controlling terminal into raw input mode, doing local echo and backspace handling in `LineEditor`.

**Consequences.** Input is shown exactly once and `:` commands never reach the emulator.  Because the debugger has no readline-style editing, local editing is limited to printable input and backspace; Ctrl-C/Ctrl-D are forwarded as raw bytes.

## ADR-0005: Parse only confirmed FS-UAE 3.2.35 output

**Context.** FS-UAE and WinUAE output formats are not guaranteed to match, and guessed formats would silently corrupt logs.

**Decision.** Implement parsing only for formats captured from real FS-UAE 3.2.35 sessions (kept in `tests/fixtures/` and documented in `fs-uae-debugger-output.md`).  Unknown lines are passed through untouched and never turned into fabricated data.

**Consequences.** The parser is small and trustworthy, but version-specific; supporting another version means capturing and verifying its output first.

## ADR-0006: Conservative, prompt-gated automatic resume

**Context.** Auto-resume must never resume the emulator after a stop the user did not configure, and must not race with typing.

**Decision.** Resume only when a hit of an explicitly configured watchpoint has been parsed *and* written to its log file, and only once the debugger prompt is reached.  Skip resume if the user has pending input, and leave the emulator stopped on any logging failure.

**Consequences.** The emulator stays under user control for unrelated stops. `_pending_resume` acts as the single gate, preventing duplicate resumes from repeated or delayed output.

## ADR-0007: Append-only CSV with a fixed schema and per-record flush

**Context.** Logging must survive interruption and be trivially inspectable, and it must not fabricate fields the debugger did not print.

**Decision.** Write UTF-8 CSV in append mode.  Write the header only when the file is created or empty, flush after every record, and record exactly the fields present in the `Memwatch ...` line plus an ISO-8601 timestamp.

**Consequences.** Files are robust and easy to diff or load.  The schema is intentionally small and specific rather than a generic logging framework.

## ADR-0008: `eventlog.py` rather than `logging.py`

**Context.** The project brief and the wrapper's own diagnostics use Python's standard `logging` module; a local module named `logging.py` inside the package would shadow it confusingly.

**Decision.** Name the CSV writer module `eventlog.py`.

**Consequences.** Import resolution stays unambiguous and readers are not misled into expecting standard-library logging behaviour.
