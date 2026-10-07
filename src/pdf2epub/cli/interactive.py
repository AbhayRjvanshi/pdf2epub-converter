"""The interactive REPL: a thin client over the command layer.

ConsoleIO is the only terminal boundary; the loop knows nothing about
conversion. Design commitments:

* **One authoritative cancellation state** -- ``self._active_token`` is set
  by the per-conversion service factory, cleared on terminal pipeline
  events, and cleared again in a ``finally`` so a raising factory or
  conversion can never leak stale cancellation into the next command.
* **Prompt vs conversion SIGINT** -- during a conversion the handler only
  cancels the token (idempotent; cooperative only, decision C1, until
  atomic output writes exist); at the prompt (or while an interactive
  command is prompting) it raises a normal ``KeyboardInterrupt`` that the
  loop absorbs without dying.
* **Convert-time configuration** -- the service factory reloads the
  current ``AppConfig`` for every conversion because commands may have
  changed persistent preferences during the session (e.g. a ``/validators``
  toggle or a ``/provider`` save). The session holds intent; fresh config
  holds execution preferences.
* **Transcript-only quiet** -- the REPL sets ``session.quiet`` so the
  engine transcript is suppressed and progress arrives through
  ``event_cb`` instead; warnings, errors and result summaries are rendered
  by the command layer regardless (``options.quiet`` only reaches the
  engine's ``verbose`` flag).
"""

from __future__ import annotations

import dataclasses
import getpass
import signal
import sys

from ..application import SessionDeps, dispatch
from ..application.session import Session
from ..config import ConfigManager
from ..engine.cancellation import CancellationToken
from ..engine.events import PipelineEvent
from ..validators import build_validator_registry, show_onboarding

_TERMINAL_EVENTS = frozenset({"completed", "failed", "cancelled"})


class ConsoleIO:
    """The real terminal boundary: input, getpass, print -- nothing else."""

    def read_line(self, prompt: str) -> str:
        return input(prompt)

    def read_secret(self, prompt: str) -> str:
        return getpass.getpass(prompt)

    def write(self, text: str) -> None:
        print(text)


def _default_service_factory(token, event_cb, deps):
    """Build the real service: fresh config, the REPL's token and renderer."""
    from ..application import ConversionService

    return ConversionService(
        registry=deps.registry,
        config=deps.config_manager.load(),  # deliberate: per-conversion prefs
        environ=deps.environ,
        event_cb=event_cb,
        cancel_token=token,
    )


class Repl:
    def __init__(
        self,
        *,
        session: Session,
        deps: SessionDeps,
        io=None,
        service_factory=None,
        onboarding: bool = True,
    ) -> None:
        self.session = session
        self.io = io if io is not None else ConsoleIO()
        self._onboarding = onboarding
        self._raw_service_factory = service_factory or _default_service_factory
        # /convert's service must receive THIS repl's renderer and token,
        # never whatever factory the deps happened to carry.
        self.deps = dataclasses.replace(deps, service_factory=self._make_service)
        self._active_token: CancellationToken | None = None
        self.session.quiet = True  # the REPL renders progress from events

    # -- service / token lifecycle ----------------------------------------
    def _make_service(self):
        token = CancellationToken()
        self._active_token = token
        return self._raw_service_factory(token, self._on_event, self.deps)

    def _on_sigint(self, signum, frame) -> None:
        token = self._active_token
        if token is None:
            raise KeyboardInterrupt  # normal Ctrl-C at the prompt
        if not token.cancelled:
            token.cancel()
            self.io.write("\ncancelling - stopping at the next checkpoint")
        # a repeated Ctrl-C just re-sets the flag: idempotent by design

    # -- event rendering ---------------------------------------------------
    def _on_event(self, event: PipelineEvent) -> None:
        if event.type in _TERMINAL_EVENTS:
            self._active_token = None  # closes the post-conversion window
            return
        if event.type == "phase_started" and event.message:
            self.io.write(f"  [{event.phase}] {event.message}")
        elif event.type == "tier2_batch_started":
            self.io.write(f"  model batch: {event.metadata.get('count')} page(s)")
        elif event.type == "validation_started":
            self.io.write("  validating...")
        elif event.type == "repair_started":
            self.io.write(f"  repair pass {event.metadata.get('attempt', 1)}")
        elif event.type == "page_progress":
            self._render_page_progress(event)

    def _render_page_progress(self, event: PipelineEvent) -> None:
        total = event.total_pages or 0
        if total <= 0 or event.page_index is None:
            return
        done = event.page_index + 1
        step = max(1, total // 10)  # deterministic: 10% boundaries + the end
        if done % step == 0 or done == total:
            self.io.write(f"  ... {done}/{total}")

    # -- the loop ----------------------------------------------------------
    def run(self) -> int:
        self.io.write(
            "pdf2epub interactive session - /help for commands, /exit to quit"
        )
        if self._onboarding:
            try:
                show_onboarding(
                    self.io,
                    self.deps.config_manager,
                    self.deps.validator_registry or build_validator_registry(),
                )
            except Exception:
                pass  # onboarding must never block the session

        previous = signal.signal(signal.SIGINT, self._on_sigint)
        try:
            return self._loop()
        finally:
            signal.signal(signal.SIGINT, previous)

    def _loop(self) -> int:
        while True:
            self._active_token = None
            try:
                try:
                    line = self.io.read_line("pdf2epub> ")
                except EOFError:
                    self.io.write("")
                    return 0
                result = dispatch(
                    line, session=self.session, io=self.io, deps=self.deps
                )
            except KeyboardInterrupt:
                # prompt interrupt, or Ctrl-C while an interactive command
                # is asking a question: clear the line and keep the session
                self.io.write("")
                continue
            finally:
                self._active_token = None
            if result.output:
                self.io.write(result.output)
            if result.exit:
                return 0


def run_repl(session, deps, *, io=None, service_factory=None, onboarding=True) -> int:
    return Repl(
        session=session,
        deps=deps,
        io=io,
        service_factory=service_factory,
        onboarding=onboarding,
    ).run()
