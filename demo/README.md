# Known symbol addresses for the Boing demo

Use those addresses to see watchpoints changes using the debugger.

| what | symbol | ADF address |
|---|---|---|
| ball X (long) | `_x` | `0x11BDE` |
| ball Y (word) + `_y_lower` (word) | `_y` | `0x11BE2` |
| X velocity | `_vx` | `0x11BE6` |
| Y velocity | `_vy` | `0x11BEA` |
| X / Y acceleration (`_ay`=1) | `_ax` / `_ay` | `0x11BEE` / `0x11BF2` |
| Y position, FFP | `_fy` | `0x11BFA` |
| rotation offset (fixed 12) | `_angoff` | `0x10248` |
| draw Y offset | `_yoff` | `0x10250` |
| run flag (0 = running) | `_sstep` | `0x10254` |
| left bounce limit (−80) | `_left` | `0x102BA` |
