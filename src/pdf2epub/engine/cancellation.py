"""Cooperative cancellation (S3).

The CLI/REPL translates ``KeyboardInterrupt`` into ``token.cancel()``; the
pipeline checks the token between pages, Tier-2 batches and repair attempts
and stops with a clean ``cancelled`` result -- never a traceback and never a
truncated EPUB. Cancellation flows only through the token.
"""

from __future__ import annotations


class CancellationToken:
    """A trivial cooperative cancellation flag."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class PipelineCancelled(Exception):
    """Internal control-flow signal; run_pipeline turns it into a result."""
