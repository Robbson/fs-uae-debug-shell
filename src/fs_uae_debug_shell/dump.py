"""Show or hide the debugger's CPU register dump on the terminal.

When the debugger stops -- on a manual activation (F12+D) or on a watchpoint
break -- it prints a CPU register dump: the ``-- stub -- activate_console``
marker, the ``D0``-``A7`` register lines, ``USP``/``ISP``, the status-register
flags ``T=00 S=1 ...``, the prefetch line, the disassembled instruction and the
``Next PC:`` line.  The dump is informational and repeats on every stop, so it
can be hidden to keep the terminal focused on the wrapper's own output.  It stays
on by default, preserving the transparent debugger view.
"""

from __future__ import annotations


class RegisterDump:
    """Whether the debugger's CPU register dump is shown on the terminal."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        """Whether the register dump block is written to the terminal."""

        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Show or hide the register dump block."""

        self._enabled = enabled
