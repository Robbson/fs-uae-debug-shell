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

**Consequences.** Input is shown exactly once and `:` commands never reach the emulator.  Cursor movement, Home/End, Backspace/Delete, and Up/Down history come from `prompt_toolkit`'s default key bindings; history is in-memory for the session only.  The wrapper depends on `prompt_toolkit` and uses `asyncio` for its input loop.  Only `prompt_toolkit` reads stdin, so there is no competing read of the terminal.  The prompt is not kept active for the whole session; it follows the debugger's own prompt (see ADR-0010).

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

**Decision.** Add a `prompt_toolkit` `Completer` (`WrapperCompleter`) that completes command names and their arguments on lines that start with the shell prefix: fixed choices for `:output`, filesystem paths for `:logfile`.  In `log` mode, render a `bottom_toolbar` status line with the running total and a counter per watchpoint.

**Consequences.** Commands are discoverable and less error-prone, and `log` mode still gives visible per-watchpoint feedback.  Completion only engages after the shell prefix, so native debugger input is untouched.  The counter lives at a fixed screen position rather than scrolling with output.

## ADR-0010: The interactive prompt is raised only at the debugger's prompt

**Context.** The wrapper originally kept a `prompt_toolkit` prompt active for the whole session.  `patch_stdout` only writes straight to the terminal when no application is running; while a prompt is up it routes every write through `run_in_terminal`, which erases the prompt, switches the terminal to cooked mode, writes, and repaints, and its flush thread sleeps a fixed debounce between batches.  FS-UAE accepts no console input while emulation runs, so a continuously active prompt repaints register and memory dumps the user cannot interact with, and watchpoint-hit streams arrive in slow, debounced pulses.

**Decision.** In `shell` and `both` mode, raise the interactive prompt only while the debugger is idle at its `>` prompt.  A `PROMPT` event sets an `asyncio.Event` (`_prompt_ready`); forwarding a command clears it until the debugger prints `>` again.  While emulation runs, and while a forwarded command's output is still arriving, no `prompt_toolkit` application is running, so `patch_stdout` writes child output straight to the terminal.  Each PTY read is written to the terminal in one `Console.write` call.  In `log` mode the prompt is instead kept raised while emulation runs, so the status line stays visible: the hit block is hidden there, so there is nothing to repaint, and the counter updates through `Console.refresh()`.

**Consequences.** In `shell`/`both` mode dumps and watchpoint-hit streams are written directly and appear at terminal speed instead of being repainted per batch, and no shell prompt is shown when FS-UAE cannot accept input.  In `log` mode the prompt (with its status line) persists across resumes, so the logged-event counter never disappears; the cost is that the prompt is up while emulation runs in that mode, and any non-hidden output printed then is rendered through the prompt.  `:help`, `:status`, `:output`, `:logfile`, and `:quit` are reachable once the debugger is active, and the wrapper depends on the debugger printing `>` to restore the prompt in `shell`/`both` mode.

## ADR-0011: Single-pass incremental parsing

**Context.** `DebuggerOutputParser.feed_pieces` re-sliced its buffer after every line, copying the remaining buffer each time — O(n²) in the chunk, and measurable on large dumps.

**Decision.** Walk the chunk with a cursor and copy only the unfinished tail once at the end, leaving the recognised formats and byte-for-byte output unchanged.

**Consequences.** Parsing a large chunk is a single pass.  Partial lines are still buffered across calls, and the prompt is still recognised without a trailing newline.

## ADR-0012: Per-frame watchpoint value selection

**Context.** The enhanced hit line prefixes each hit with a video-frame counter.  A frame can contain several writes to the same watchpoint (the game loop runs more often than frames are rendered), but the screen shows only one of those values.  Showing and logging every write produces far more rows than the rendered state, and neither the first nor the last write is universally the meaningful one.

**Decision.** Group hits by `(frame, watchpoint)` and keep the `first`, `last`, or `all` of them (`FrameValueSelector` in `frames.py`), selected with `:framevalues` and defaulting to `first`.  `first` drops later occurrences in the same frame, `last` buffers the frame and emits one hit per watchpoint when the frame number changes, and `all` keeps every hit.  A hit without a frame counter (classic output) ignores the mode and is always emitted.  The selector is flushed on a frame boundary, on any other structured event, and at shutdown.

**Consequences.** The terminal and the CSV log show the per-frame value the user chooses rather than every intermediate write, matching what is rendered and keeping logs small.  `last` is emitted when the next frame's first hit arrives, so it renders up to one frame late, and a sparse watchpoint's final value appears only at the next event or at shutdown.  The parser treats the frame counter as decimal; a hexadecimal counter would require a parser change first.

## ADR-0013: Frame condensation with a wide per-frame CSV schema

**Context.** The enhanced hit stream is verbose: every write becomes a full `Memwatch` line, and a run with several watchpoints is hard to read frame by frame.  The user wants an alternative view that keeps only the frame, the watchpoint ids, and their values, with one line per frame and one column per watchpoint.  This changes the CSV shape too: a per-hit row cannot express "all watchpoints of a frame".

**Decision.** Add a `FrameAggregator` (`aggregate.py`) after the per-frame value selector.  It groups the selected hits of a frame and emits one `AggregatedFrame`; `format_frame_line` renders it as `<frame> <wp>:<value> ...`, printing every known watchpoint column so a missing value stays blank rather than looking carried over.  The CSV writer gains a wide schema (`timestamp,frame,wp1,wp2,...`), selected by `OutputRouter.record_frame` versus `record`.  Columns are the watchpoint ids known from parsed definitions plus those seen in hits, fixed when the file is created.  `:frameagg on|off` controls the feature and defaults to `on`.  Only hits with a frame counter are aggregated; classic hits pass through unchanged.

**Consequences.** The terminal and the log show one compact row per frame, matching the requirement, and `:framevalues` still governs which write of each watchpoint is kept before condensation.  Because the header is fixed at file creation, a watchpoint that first appears later is a reported logging error rather than a silently dropped value, and toggling `:frameagg` (or changing the output shape) while a file is open starts a new file.  A repeated watchpoint in one frame keeps its last selected value, so `:framevalues all` still yields a single cell per watchpoint.
