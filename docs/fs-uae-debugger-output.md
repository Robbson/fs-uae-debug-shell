# Observed FS-UAE 3.2.35 debugger output

All formats below were captured from real FS-UAE 3.2.35 sessions on Linux (`fs-uae --load_state=2 ~/FS-UAE/Configurations/HotShot.fs-uae`).  The raw captures are committed as test fixtures:

- `tests/fixtures/watchpoint_session.txt` — one activation followed by eight consecutive watchpoint hits.
- `tests/fixtures/watchpoint_session_1.txt` — a single watchpoint hit.

## Activating the debugger

Activated manually with F12+D.  A watchpoint hit produces no `WARNING: Activated debugger` line; it starts with a `Memwatch` line instead.

```text
WARNING: Activated debugger
 -- stub -- activate_console
  D0 00000DB9   D1 00000028   D2 0000FFFF   D3 00000000
  D4 00001717   D5 000AFFFF   D6 FB5F0003   D7 0000FFFF
  A0 0000EDB8   A1 0000070A   A2 00000574   A3 00000079
  A4 0007AC34   A5 000161E0   A6 00078342   A7 0007FFF8
USP  00C0BEF4 ISP  0007FFF8
T=00 S=1 M=0 X=0 N=0 Z=1 V=0 C=0 IMASK=3 STP=0
Prefetch fffe (ILLEGAL) 48e7 (MVMLE) Chip latch 0000FFFE
00008A6A 48e7 fffe                MOVEM.L D0-D7/A0-A6,-(A7)
Next PC: 00008a6e
>
```

The prompt is a bare `>` at the start of a line.  It is **not** newline terminated, so the parser recognises it as soon as it appears at a line start.

## Adding a watchpoint

```text
>w 0 $574 2 W
Memwatch breakpoints enabled
 0: 00000574 - 00000575 (2)  W  CPU
```

- `Memwatch breakpoints enabled` is a fixed line.
- The definition line has the form ` <id>: <start> - <end> (<length>)  <access>  <scope>`.

`fl` lists *breakpoints* (not watchpoints) and prints `No breakpoints`.

## Watchpoint hit

```text
Memwatch 0: break at 00000574.W  W  000000FB PC=0000B8A6 CPUDW (000)
 -- stub -- activate_console
  D0 BB4EFFF9   D1 00000008   D2 00000010   D3 0000FFFF
  ...
Next PC: 0000b8ba
>
```

Grammar of the hit line:

```text
Memwatch <id>: break at <addr>.<size>  <access>  <value> PC=<pc> <trailer>
```

- `<id>`: watchpoint id (decimal).
- `<addr>`: 8 hex digits.
- `<size>`: `B`, `W` or `L` (observed `W` for a word watchpoint).
- `<access>`: `R`, `W`, `I`, `F` or `C` (observed `W` for a write watchpoint).
- `<value>`: 8 hex digits.
- `<pc>`: 8 hex digits.
- `<trailer>`: informational only (observed `CPUDW (000)`).

A hit is followed by the same register dump / disassembly / `Next PC` block as a manual activation, ending in the `>` prompt.  Automatic resume must wait for that prompt before sending `g`.

## Terminal echo

In a plain FS-UAE session the child PTY has kernel echo enabled, so typed commands are echoed back (`>r`, `>g`, ...).  The wrapper disables child echo and performs its own local echo so that intercepted `:` commands are never echoed by the emulator and commands are not shown twice.
