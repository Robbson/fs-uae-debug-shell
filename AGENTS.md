# Project: FS-UAE Debug Wrapper

## 1. Overview

_FS-UAE Debug Wrapper_ is a Python-based interactive wrapper around the FS-UAE console debugger on Linux. It keeps the native debugger fully usable while adding automation: monitoring memory watchpoints, parsing debugger output, and logging watchpoint hits to CSV files.

The wrapper is an automation layer on top of the existing debugger, not a replacement for it.  With all automation disabled it must still behave like an ordinary interactive debugger.

## 2. Fundamental principles

These hold for the whole life of the project and must not be tied to a particular milestone or phase.

- **Transparent by default.** Forward ordinary debugger commands to FS-UAE unchanged and show debugger output in the terminal as it arrives. Do not reimplement, reinterpret, rewrite, or filter native debugger commands. Interactivity must be preserved while FS-UAE is running or stopped.
- **Automation is opt-in and additive.** Extra behaviour must never change what the user sees or can do unless the user explicitly configured it, and is triggered only by recognized, explicitly configured events.
- **Only confirmed behaviour.** Base parsing and automation on output verified from real FS-UAE sessions.  Never invent formats or assume WinUAE semantics are identical. Support what is confirmed for the target version and fail safely on anything else.
- **Explicit state.** Track session/debugger state explicitly (running, stopped at the prompt, shutting down) and refine it against observed FS-UAE behaviour. Do not infer that emulation stopped merely because a line contains a word such as "watch" or "break".
- **Fail visible and safe.** Report errors so they are visible and actionable. When the state is uncertain or a step fails, stop automation and return control to the user instead of guessing. Never silently discard debugger output.

- **Observability over cleverness.** Prefer simple, understandable behaviour. Keep wrapper messages clearly distinguishable from FS-UAE console output.
- **Do not alter emulated state.** Never change emulated memory or execution state.  Do not modify FS-UAE itself.

## 3. Behaviour

### 3.1 Transparent interactive wrapper

- The debugger is not active at FS-UAE startup.  It becomes active when the user presses F12 + D, or when a watchpoint triggers a break.  Activation prints `WARNING: Activated debugger`, then a register dump, then the interactive `>` prompt.
- Forward all non-wrapper input to FS-UAE unchanged; support commands that produce multiple lines of output.
- Avoid unnecessary buffering or added latency; read child output continuously without blocking input.
- Handle Ctrl-C, EOF, process termination, and unexpected child-process exits.
- Clean up child processes and file handles on shutdown; never leave FS-UAE running unintentionally.

### 3.2 Wrapper commands

- Reserve a configurable prefix (default `:`) for wrapper-specific commands; they must never reach the emulator.
- Validate arguments and report useful errors.
- Keep wrapper commands out of the FS-UAE command namespace; all non-wrapper input passes through unchanged.
- Document every wrapper command in `README.md`.

### 3.3 Watchpoint logging

The user creates watchpoints with the native debugger (`w`); the wrapper observes hits.

When a configured watchpoint causes a break, the wrapper recognizes the event, parses the hit, and appends a record to the configured log file.  Parsing and logging must be based on output confirmed for the target FS-UAE version; unparsed fields are reported, never fabricated.

The wrapper never resumes emulation automatically: a hit leaves the emulator stopped at the debugger prompt, and the user continues with `g`.  Debugger output is shown unchanged.

### 3.4 Log file format

- CSV, UTF-8, append-only.  Write a header only when the file is newly created or empty, and flush so recent records survive an interruption.
- Include a timestamp when one can be obtained reliably, plus the watchpoint id.
- Record the address, access type, and value only when the observed output supports them; distinguish unavailable values from genuine zeros.
- Handle file creation errors, permissions, and invalid paths explicitly.
- Favour a small, well-defined schema over a generic logging framework.

## 4. Tooling and environment

- Python, managed with `uv`.  Preserve the existing `pyproject.toml` and `uv.lock`; use `uv` for dependency management and for running the code.  Do not switch package managers.
- Add dependencies only when clearly justified and explained; keep the set minimal.  `pexpect` and `prompt_toolkit` are the only declared runtime dependencies.
- Target Linux and a POSIX terminal; talk to FS-UAE through `pexpect` and a pseudo-terminal.
- Primary target: the interactive FS-UAE 3.2.35 console debugger on Linux.
- Use Python's standard `logging` for wrapper diagnostics.

## 5. Development and test environment

- `fs-uae` is available on `PATH`.  Start the target game with:

  ```
  fs-uae --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae
  ```

  Do not scan the filesystem for FS-UAE configurations; use exactly these arguments.  The configuration is already prepared for terminal debugging.
- The debugger cannot be activated programmatically.  Ask the user to press F12 + D once the game is running, and state clearly when human interaction is required.
- Permanently changing variables that are useful for watchpoint testing; ball position (x, y, vx, vy):
  - `$574` (word), `$576` (word), `$580` (word), `$582` (word).

## 6. Architecture

Keep the implementation modular with clear boundaries between terminal handling, session/process management, debugger output parsing, watchpoint logging, and wrapper commands.  Avoid circular dependencies and global mutable state where practical.

`docs/architecture.md` describes the current structure, modules, state model, and data flow.  `docs/decisions.md` records why that structure was chosen. Keep both in step with the code.

## 7. Concurrency and state

- Handle user input and debugger output concurrently with a straightforward design that works reliably with `pexpect` and POSIX terminals.  Interactive input is provided by `prompt_toolkit` (which runs on `asyncio`); do not add further asynchronous frameworks or concurrency libraries without a demonstrated need.
- Debugger output can arrive in partial chunks, and one logical event may span several lines; parse incrementally.
- A debugger prompt may appear before or after relevant output; the wrapper never sends commands on its own, so there is no race with user input.
- Use explicit, named states and transitions rather than implicit behaviour.

## 8. Error handling and diagnostics

Errors must be visible and actionable.  Examples: FS-UAE executable not found; the child process exits unexpectedly; debugger output cannot be parsed; a watchpoint id is unknown; a log file cannot be opened or written.

- Do not swallow exceptions or suppress important debugger output.
- Use standard `logging` for wrapper diagnostics, keeping wrapper messages distinguishable from FS-UAE console output.
- When synchronization with the debugger is lost, stop automation and return control to the user rather than attempting speculative recovery.

## 9. Code quality

- Follow idiomatic modern Python and use type hints for public functions and important data structures.
- Keep functions focused and reasonably small; prefer explicit state transitions over implicit behaviour.
- Avoid unnecessary abstractions and premature generalization; keep dependencies minimal.
- Preserve the existing `uv` configuration.
- Run the available tests and relevant lint/type checks before considering work complete.  If a check cannot be run, explain why.

## 10. Testing

- Unit-test logic that does not require a running emulator, in particular: debugger output parsing (including partial and multi-line output), wrapper command parsing and dispatch, watchpoint logging configuration management, CSV creation/appending and errors, hit handling, unrelated debugger stops, logging failures, and process termination/cleanup.
- Use captured FS-UAE output in `tests/fixtures/` as fixtures wherever possible.
- Prefer deterministic synchronization over arbitrary timing delays.
- Do not claim that integration tests pass unless they have actually been run.

## 11. Documentation

Keep documentation in step with the code.  Update the relevant documents in the same change as the code they describe.

| Document | Purpose |
| --- | --- |
| `AGENTS.md` | How to work on the project (this file): fundamental, lifespan-long instructions. |
| `README.md` | What the project does: install, usage, commands, limitations. |
| `docs/architecture.md` | The structure of the project: modules, state model, data flow. |
| `docs/decisions.md` | Why the structure and behaviour are as they are (decision records). |
| `docs/fs-uae-debugger-output.md` | Verified FS-UAE debugger output formats and fixtures. |
| `CHANGELOG.md` | What has changed, newest first. |

Rules:

- Every completed feature or behavioural change gets a short entry in `CHANGELOG.md` (under `Unreleased` while in development).
- Structural changes update `docs/architecture.md`.
- Non-obvious technical decisions get a decision record in `docs/decisions.md` (context, decision, consequences).
- User-facing changes update `README.md`.
- Keep this file general: do not add dated, phase-specific, or one-off instructions here.
- Do not hard-wrap prose: put each paragraph on one line and let the editor soft-wrap.
