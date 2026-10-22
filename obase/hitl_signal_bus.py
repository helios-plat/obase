"""Synchronous human-in-the-loop interrupt signal channel.

This small state holder is deliberately independent of an event loop so a UI,
signal handler, or operator can trigger an interruption while an agent loop
checks it at its next checkpoint.
"""

from __future__ import annotations


class HitlSignalBus:
    """Hold the latest user-interrupt signal for an injected agent loop."""

    def __init__(self) -> None:
        self.interrupted = False
        self.interrupt_reason = ""

    def signal_interrupt(self, reason: str = "user interrupt") -> None:
        """Publish an interrupt and an optional human-readable reason."""
        if not isinstance(reason, str):
            raise TypeError("reason must be a string")
        self.interrupt_reason = reason.strip() or "user interrupt"
        self.interrupted = True

    def clear_interrupt(self) -> None:
        """Clear the pending interrupt before an explicitly resumed turn."""
        self.interrupted = False
        self.interrupt_reason = ""
