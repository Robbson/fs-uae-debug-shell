# Project: FS-UAE Debug Wrapper

## 1. Project Overview

Build a Python-based interactive wrapper around the FS-UAE console debugger on Linux.

The wrapper should preserve the normal FS-UAE debugger workflow while adding automation capabilities for monitoring memory watchpoints, parsing debugger output, logging relevant values to files, and automatically resuming emulation after selected debugger breaks.

The primary motivation is that the FS-UAE debugger appears to lack some of the logging-only functionality available in WinUAE. Memory watchpoints that stop emulation should be usable for continuous logging without requiring manual intervention for every hit.

The project is an automation layer around the existing debugger, not a replacement for it.

## 2. Existing Project Setup

* A Python project has already been initialized using `uv`.
* `pexpect` is already declared as a project dependency.
* Preserve the existing project configuration.
* Use `uv` for dependency management and running the application.
* Do not replace `uv` with another package manager.
* Do not introduce additional dependencies unless they provide a clear benefit and the need is explained.
* Target Linux and the interactive FS-UAE console debugger, initially FS-UAE 3.2.35.

Inspect the existing project structure and configuration before making changes. Follow established conventions where possible.

## 3. Core Requirements

### 3.1 Transparent Interactive Debugger

The wrapper must allow users to interact with the FS-UAE debugger almost exactly as they would when launching FS-UAE directly from a terminal.

But keep in mind that the debugger is not started automatically after the start of FS-UAE. So interaction is only allowed when

1. the user decides to switch on the debugger in the UI using the F12 + D shortcut
2. A watchpoint is triggered

When the debugger gets activated it is going to pause the emulator and prints this line in the terminal: 
```
WARNING: Activated debugger
```
After some additional output like the CPU registers and PC the interactive shell is going to start. This can be clearly recognized by the leading ">" sign of each row.

Requirements:

* Forward ordinary debugger commands to FS-UAE unchanged.
* Display debugger output in the user's terminal as it arrives.
* Preserve interactive command entry while FS-UAE is running or stopped.
* Support commands that produce multiple lines of output.
* Handle terminal prompts and debugger state transitions reliably.
* Avoid unnecessary buffering or delays.
* Preserve the original debugger's functionality wherever possible.

The wrapper must not attempt to reimplement or interpret ordinary debugger commands unless explicitly required for an additional feature.

### 3.2 Process and Terminal Management

Use `pexpect` and a pseudo-terminal (PTY) to interact with FS-UAE.

The implementation must:

* Launch FS-UAE as a child process when appropriate.
* Allow configurable FS-UAE executable paths and command-line arguments.
* Preserve the terminal behavior required by the FS-UAE console debugger.
* Forward user input to the child process.
* Read child output continuously without blocking user input.
* Handle terminal echo carefully to avoid duplicated commands or output.
* Handle Ctrl-C, EOF, process termination, and unexpected child-process exits.
* Clean up child processes and file handles on shutdown.
* Avoid leaving FS-UAE running unintentionally after the wrapper exits.

Do not assume that FS-UAE always emits a predictable prompt or that every output line represents a complete logical message.

If FS-UAE is already running or is launched externally, do not assume that its console can be attached to afterward. Document the supported launch and attachment model explicitly.

### 3.3 Custom Wrapper Commands

Reserve a configurable command prefix, initially `:`, for wrapper-specific commands.

Examples:

```text
:help
:logwatch 0 score.csv
:logoff 0
:status
```

Requirements:

* Intercept wrapper commands before forwarding input to FS-UAE.
* Forward all non-wrapper commands unchanged.
* Keep wrapper commands separate from FS-UAE's command namespace.
* Validate arguments and report useful errors.
* Ensure that wrapper commands do not accidentally reach the emulator.
* Document all supported wrapper commands.

The examples above define the intended interface, not necessarily the complete initial implementation.

### 3.4 Watchpoint Logging

Provide a mechanism for associating a logging configuration with a debugger memory watchpoint.

Example:

```text
w 0 $123456 2 W
:logwatch 0 score.csv
```

The intended behavior is:

1. The user configures a memory watchpoint using the native FS-UAE debugger.
2. The user enables automatic logging for that watchpoint.
3. When the watchpoint causes a debugger break, the wrapper recognizes the event.
4. The wrapper extracts relevant information from the debugger output.
5. The wrapper appends a record to the configured log file.
6. The wrapper automatically sends `g` to resume emulation.
7. The process repeats for subsequent matching breaks.

This feature must be based on observed and verified FS-UAE behavior.

Do not assume that the debugger's output format, prompt, or watchpoint semantics are identical across FS-UAE and WinUAE versions.

Initially, support only the output formats that have been confirmed through real FS-UAE 3.2.35 sessions.

### 3.5 Safe Automatic Resume

Automatic resume is a central feature, but it must not interfere with normal interactive debugging.

Requirements:

* Only resume automatically when a recognized, explicitly configured logging event has been handled successfully.
* Do not automatically resume after an unrelated breakpoint, exception, or debugger stop.
* Do not automatically resume when the wrapper cannot reliably identify the current debugger state.
* Do not silently discard debugger output.
* Provide a way to disable automatic resume and return to manual control.
* Clearly report parsing errors and logging failures.
* If logging fails, default to leaving the emulator stopped rather than losing data and continuing silently.
* Avoid sending repeated `g` commands because of duplicated or delayed output.

A logging-enabled watchpoint must never cause the wrapper to blindly resume after an arbitrary debugger break.

### 3.6 Log File Format

Use CSV for the initial logging implementation.

Requirements:

* Append records instead of overwriting existing logs.
* Write a header when creating a new, empty log file.
* Use a consistent encoding, preferably UTF-8.
* Flush output appropriately so that recent records survive a process interruption.
* Include a timestamp when a reliable timestamp can be obtained.
* Include the watchpoint identifier when known.
* Record the parsed address, access type, and value only when supported by the observed debugger output.
* Distinguish unavailable or unparsed fields from genuine zero values.
* Handle file creation errors, permissions, and invalid paths explicitly.

Do not fabricate values that are not present in the debugger output.

The initial implementation should favor a small, well-defined CSV schema over an overly generic logging framework.

## 4. Architecture

Keep the implementation modular, with clear boundaries between terminal interaction, debugger output processing, watchpoint logging, and custom commands.

Suggested modules:

```text
main.py
cli.py
session.py
terminal.py
parser.py
commands.py
watchpoints.py
logging.py
```

Adapt this structure to the existing project rather than restructuring it unnecessarily.

Responsibilities:

* `cli.py`: Parse command-line arguments and configure the application.
* `session.py`: Manage the FS-UAE process and debugger session.
* `terminal.py`: Handle interactive input, output forwarding, and terminal behavior.
* `parser.py`: Parse observed debugger output into structured events.
* `commands.py`: Implement wrapper-specific commands.
* `watchpoints.py`: Manage watchpoint logging configurations and automatic resume policies.
* `logging.py`: Write structured events to CSV files.

Avoid circular dependencies and global mutable state where practical.

Use type hints and clear interfaces between modules.

## 5. Event Handling and Concurrency

The wrapper must handle user input and debugger output concurrently.

Use a straightforward architecture that works reliably with `pexpect` and POSIX terminals. Do not introduce asynchronous frameworks or additional concurrency libraries without a demonstrated need.

Important considerations:

* Debugger output can arrive in partial chunks.
* One logical event can span several output lines.
* Output can be delayed or interleaved with terminal echo.
* A debugger prompt may appear before or after relevant output.
* The user may enter commands while output is being received.
* Automatic resume must not race with user input.
* Multiple watchpoints may be configured simultaneously.

Use explicit state management for debugger states such as running, stopped, waiting for a command, and shutting down. Refine these states as required by actual FS-UAE behavior.

Do not infer that emulation is stopped solely because an arbitrary output line contains a word such as "watch" or "break".

## 6. Development Phases

Implement the project incrementally.

### Phase 1: Transparent Wrapper

* Inspect the existing project.
* Implement launching FS-UAE through `pexpect`.
* Forward user input and debugger output.
* Preserve interactive terminal behavior.
* Handle process shutdown and common error cases.
* Verify that ordinary debugger commands work unchanged.

Do not implement automatic parsing or resume until this phase is reliable.

### Phase 2: Capture and Understand Debugger Output

* Capture representative output from real FS-UAE 3.2.35 sessions.
* Document the output associated with a watchpoint hit.
* Identify reliable indicators for debugger stops, prompts, and resumed execution.
* Determine how terminal echo affects parsing.
* Add parser tests using captured output fixtures.

Do not invent output formats or rely exclusively on assumed WinUAE behavior.

### Phase 3: Custom Commands

* Implement `:help` and `:status`.
* Add a command parser with explicit argument validation.
* Ensure ordinary commands are still passed through unchanged.
* Add unit tests for command dispatch and invalid input.

### Phase 4: Manual Watchpoint Logging

* Implement `:logwatch` and `:logoff`.
* Associate logging configurations with watchpoint identifiers.
* Parse confirmed watchpoint output formats.
* Append structured records to CSV files.
* Report malformed events and file errors without losing control of the debugger.

Initially, logging should not automatically resume emulation. Allow the user to inspect the parsed events and validate the output.

### Phase 5: Automatic Resume

* Add automatic resume for recognized, configured logging events.
* Send `g` only after successful parsing and logging.
* Preserve manual control for unrelated stops.
* Add safeguards against repeated resume commands and state-transition races.
* Test multiple consecutive watchpoint hits.

### Phase 6: Documentation and Robustness

* Document installation, configuration, and usage.
* Document known FS-UAE limitations.
* Add regression tests for terminal behavior, parsing, logging, and process shutdown.
* Verify behavior against the actual target version.

## 7. Testing Strategy

Use unit tests for logic that does not require a running emulator.

Prioritize tests for:

* Debugger output parsing.
* Partial and multi-line output.
* Wrapper command parsing.
* Watchpoint configuration management.
* CSV creation and appending.
* Invalid logging configurations.
* Automatic resume decisions.
* Handling unrelated debugger stops.
* Logging failures.
* Process termination and cleanup.

Use captured FS-UAE output as fixtures wherever possible.
The program is available as _fs-uae_. Please use the following command line parameters to start the program.
```
fs-uae --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae
```
This brings you directly to a running game. DON'T scan the filesystem for any kind of fs-uae configuration, just use those parameters. The config is already prepared for terminal debugging.

Ask the user to activate the debugger if necessary because there is no automatic way doing so at startup.
You can use the following addresses to watch some permanently changing variables:
Ball position (x, y, vx, vy)
$574 (word)
$576 (word)
$580 (word)
$582 (word)

Do not claim that integration tests pass unless they have actually been run. 
Avoid tests that depend on arbitrary timing delays when a deterministic synchronization mechanism is available.

## 8. Error Handling and Diagnostics

Errors must be visible and actionable.

Examples include:

* FS-UAE executable not found.
* Child process exits unexpectedly.
* Debugger output cannot be parsed.
* Watchpoint identifier is unknown.
* Log file cannot be opened or written.
* Automatic resume is unsafe because the debugger state is uncertain.

Do not silently swallow exceptions or suppress important debugger output.

Use Python's standard logging facilities for wrapper diagnostics, while keeping the FS-UAE console output distinguishable from wrapper-generated messages.

## 9. Code Quality

* Follow idiomatic modern Python.
* Use type hints for public functions and important data structures.
* Keep functions focused and reasonably small.
* Prefer explicit state transitions over implicit behavior.
* Avoid unnecessary abstractions and premature generalization.
* Keep dependencies minimal.
* Preserve the existing `uv` configuration.
* Run the available tests and relevant lint or type checks before completing changes.
* Explain any checks that could not be run.

Do not modify FS-UAE itself as part of the initial implementation.

The first implementation should be a standalone wrapper. Patching FS-UAE may be considered later if the native debugger does not expose enough information for reliable logging.

## 10. Safety and Data Integrity

The wrapper must not modify emulated memory unless the user explicitly enters a native debugger command that does so.

Do not reinterpret or rewrite native debugger commands.

Do not automatically issue commands that change memory, reset the emulator, or alter execution state beyond the explicitly configured resume behavior.

If the wrapper loses synchronization with the debugger, prefer stopping automation and returning control to the user over attempting speculative recovery.

## 11. Definition of Done

The initial project is successful when:

1. FS-UAE can be launched through the wrapper.
2. The native debugger remains usable interactively.
3. Ordinary debugger commands are forwarded unchanged.
4. Debugger output is visible without significant delay.
5. Wrapper-specific commands do not interfere with native commands.
6. A confirmed memory-watchpoint hit can be parsed and appended to a CSV file.
7. Automatic resume works for configured watchpoint events only.
8. Unrelated debugger stops remain under user control.
9. The implementation includes tests for parsing, logging, and resume decisions.
10. Installation and usage are documented.

When working on this repository, prioritize correctness and observability over cleverness. The wrapper must remain useful as an ordinary interactive debugger even when all automation features are disabled.
