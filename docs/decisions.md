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

**Superseded by ADR-0009** (the input prompt now runs on an `asyncio` loop).

## ADR-0004: Disable child echo and do local line editing

**Context.** In a plain FS-UAE session the PTY has kernel echo enabled, so typed commands are echoed back.  If the wrapper also echoed, input would appear twice, and intercepted `:` commands would still reach the emulator's echo.

**Decision.** Spawn FS-UAE with `echo=False` and put the controlling terminal into raw input mode, doing local echo and backspace handling in `LineEditor`.

**Consequences.** Input is shown exactly once and `:` commands never reach the emulator.  Because the debugger has no readline-style editing, local editing is limited to printable input and backspace; Ctrl-C/Ctrl-D are forwarded as raw bytes.

**Superseded by ADR-0009** for the line-editing part; child echo stays disabled.

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

## ADR-0009: `prompt_toolkit` for interactive input

**Context.** The original input layer was a hand-written raw-mode line editor that only understood printable input and backspace.  Practical editing (cursor movement, Home/End, Delete) and command history were missing, and asynchronous debugger output could disturb the line being typed.

**Decision.** Provide the input line with `prompt_toolkit`'s `PromptSession`, driven by an `asyncio` loop.  The child PTY is read with `loop.add_reader` and its output is rendered above the prompt with `patch_stdout(raw=True)`; `Console` in `terminal.py` wraps this.  `pexpect` keeps ownership of the child PTY.  This supersedes ADR-0003 and the line-editing part of ADR-0004.

**Consequences.** Cursor movement, Home/End, Backspace/Delete, and Up/Down history come from prompt_toolkit's default key bindings; history is in-memory for the session only.  The wrapper now depends on `prompt_toolkit` and uses `asyncio` for its input loop (the demonstrated need required by AGENTS.md).  Only prompt_toolkit reads stdin, so there is no competing read of the terminal.

## ADR-0010: Quiet output for automatically logged watchpoint hits

**Context.** Every watchpoint break makes FS-UAE print a register dump, disassembly, and `Next PC` block before its prompt.  During continuous logging this floods the terminal on every iteration and buries the `Memwatch ...` lines the user actually wants.  The wrapper also printed its own per-hit summary line for the same hit.

**Decision.** By default the wrapper displays only the `Memwatch ... break at ...` line for a hit it logs and will automatically resume, suppresses the generic block and the prompt until the end of that block, and does not print its per-hit summary line.  `--show-watchpoint-dump` restores the register dump and the summary.  Output that is not part of an automatic iteration (unconfigured hits, manual activations, `:auto off`) is always shown in full.

**Consequences.** While logging, the terminal shows a clean stream of watchpoint lines.  This deliberately hides some debugger output, so it is documented and configurable rather than silent: the raw `Memwatch` line is never hidden, the automated parsing/resume logic still sees the full stream, and `--show-watchpoint-dump` trades the clean view back for transparency.

## ADR-0011: `:wwcl` with a wrapper-side change filter

**Context.** FS-UAE's `w` command accepts a watchpoint "must change" (`C`) flag, but it does not work reliably: every write to the watched address breaks, whether or not the value changed.  The user needs a log of real changes only, and the native `w` syntax is verbose to type.

**Decision.** Add `:wwcl <id> <name> <address> <length>[, ...]`.  It expands to native `w <id> $<addr> <len> W` commands, enables CSV logging automatically, and records the watch names.  The log file is generated as `<name1>_<name2>_NNN.csv`, using the next free counter in the working directory.  `WatchpointManager` keeps the last value seen for each watch and drops hits whose value is unchanged: those are neither logged nor displayed, although emulation is still resumed.  The watch `name` is written as a CSV column.

**Consequences.** Users get change-only logs and a compact command.  The filter lives in the wrapper rather than FS-UAE, so it depends on comparing parsed hit values; only `:wwcl`-created watches are filtered, and plain `:logwatch` watches keep logging every hit.  Generated filenames avoid overwriting earlier sessions but tie output to the working directory and require watch names to be filesystem-safe.
