"""Pipeline events (S2): structured progress/failure telemetry.

Consumers (CLI, REPL, future UIs) receive these through the optional
``event_cb`` argument of :func:`run_pipeline`. A callback that raises is
logged and ignored -- a UI bug must never abort a conversion. Cancellation
is signalled separately (see :mod:`pdf2epub.engine.cancellation`), never by
raising from a callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Event vocabulary:
#   phase_started | page_progress | tier2_batch_started | validation_started
#   | repair_started | completed | cancelled | failed


@dataclass(frozen=True)
class PipelineEvent:
    type: str
    phase: int
    page_index: int | None = None
    total_pages: int | None = None
    message: str = ""
    metadata: dict = field(default_factory=dict)
