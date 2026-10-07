"""Phase 14: the REPL - thin loop, token lifecycle, deterministic rendering.

No real signals and no real terminals: ConsoleIO delegation is unit-tested,
every loop path is driven through a scripted IO (which can raise
KeyboardInterrupt as a line), and signal installation is patched out.
"""

from pathlib import Path

import pytest

import pdf2epub.cli.interactive as interactive
from pdf2epub.application import ConversionResult, SessionDeps
from pdf2epub.application.session import Session
from pdf2epub.cli.interactive import ConsoleIO, Repl
from pdf2epub.config import AppConfig
from pdf2epub.engine.cancellation import CancellationToken
from pdf2epub.engine.events import PipelineEvent
from pdf2epub.providers.registry import build_registry


@pytest.fixture(autouse=True)
def _no_real_signals(monkeypatch):
    monkeypatch.setattr(interactive.signal, "signal", lambda signum, handler: None)


class FakeIO:
    def __init__(self, lines=(), secrets=()):
        self._lines = list(lines)
        self._secrets = list(secrets)
        self.written = []
        self.prompts = []

    def read_line(self, prompt):
        self.prompts.append(prompt)
        if not self._lines:
            raise EOFError
        item = self._lines.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def read_secret(self, prompt):
        return self._secrets.pop(0) if self._secrets else ""

    def write(self, text):
        self.written.append(text)

    @property
    def text(self):
        return "\n".join(self.written)


class FakeConfigManager:
    def __init__(self, config=None):
        self._config = config or AppConfig(validators_notice="never")
        self.loads = 0
        self.saved = []
        self._path = Path("config.toml")

    def load(self):
        self.loads += 1
        return self._config

    def save(self, updates):
        self.saved.append(updates)
        return self._config

    def path(self):
        return self._path


class FakeService:
    def __init__(self, result=None, on_convert=None):
        self.result = result or ConversionResult(
            success=True, output_path=Path("out.epub")
        )
        self.on_convert = on_convert
        self.requests = []

    def convert(self, request, *, explicit_secret=None):
        self.requests.append(request)
        if self.on_convert is not None:
            return self.on_convert(request)
        return self.result


def _deps(config_manager=None, service_factory=None):
    return SessionDeps(
        registry=build_registry(),
        config_manager=config_manager or FakeConfigManager(),
        service_factory=service_factory,
        environ={},
    )


def _ready_session(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "book.pdf", title=None, author=None)
    session.set_output(tmp_path / "out.epub")
    session.select_provider("none")
    return session


def _builder(*, result=None, on_convert=None):
    services = []

    def factory(token, event_cb, deps):
        service = FakeService(result=result, on_convert=on_convert)
        service.token = token
        service.event_cb = event_cb
        services.append(service)
        return service

    return factory, services


# -- ConsoleIO ---------------------------------------------------------------

def test_console_io_delegates(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: f"<{prompt}>")
    monkeypatch.setattr(interactive.getpass, "getpass", lambda prompt: "secret")
    io = ConsoleIO()
    assert io.read_line("p> ") == "<p> >"
    assert io.read_secret("key: ") == "secret"
    io.write("hello")
    assert "hello" in capsys.readouterr().out


# -- the loop ----------------------------------------------------------------

def test_loop_dispatches_and_exits():
    repl = Repl(session=Session(), deps=_deps(), io=FakeIO(lines=["/help", "/exit"]))
    assert repl.run() == 0
    assert "Available commands" in repl.io.text


def test_eof_exits_cleanly():
    repl = Repl(session=Session(), deps=_deps(), io=FakeIO(lines=[]))
    assert repl.run() == 0


def test_prompt_ctrl_c_clears_the_line_and_continues():
    io = FakeIO(lines=[KeyboardInterrupt(), "/exit"])
    repl = Repl(session=Session(), deps=_deps(), io=io)
    assert repl.run() == 0
    assert len(io.prompts) == 2  # interrupted prompt, then /exit
    assert "bye" in repl.io.text  # the session kept going until /exit


def test_ctrl_c_while_a_command_prompts_is_survivable():
    # /select asks for a path; Ctrl-C there must not kill the REPL
    io = FakeIO(lines=["/select", KeyboardInterrupt(), "/exit"])
    repl = Repl(session=Session(), deps=_deps(), io=io)
    assert repl.run() == 0
    assert "/select" in "".join(io.written) or "PDF path" in "".join(io.prompts)


# -- service factory wiring --------------------------------------------------

def test_factory_receives_a_fresh_token_and_the_renderer(tmp_path):
    factory, services = _builder(
        result=ConversionResult(success=True, warnings=["w1"])
    )
    repl = Repl(
        session=_ready_session(tmp_path),
        deps=_deps(),
        io=FakeIO(lines=["/convert", "/exit"]),
        service_factory=factory,
    )
    assert repl.run() == 0
    assert len(services) == 1
    assert isinstance(services[0].token, CancellationToken)
    assert callable(services[0].event_cb)
    # transcript-only quiet: the request carries it, warnings still render
    assert services[0].requests[0].options.quiet is True
    assert "warning: w1" in repl.io.text


def test_default_factory_loads_config_per_conversion(monkeypatch):
    constructed = []

    class _FakeConversionService:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

    monkeypatch.setattr(
        "pdf2epub.application.ConversionService", _FakeConversionService
    )
    manager = FakeConfigManager()
    deps = _deps(config_manager=manager)
    interactive._default_service_factory(CancellationToken(), lambda e: None, deps)
    interactive._default_service_factory(CancellationToken(), lambda e: None, deps)
    assert manager.loads == 2  # a fresh AppConfig at every conversion
    assert constructed[0]["config"] is manager._config
    assert constructed[0]["cancel_token"] is not None


# -- token lifecycle ---------------------------------------------------------

def test_ctrl_c_mid_conversion_cancels_and_session_survives(tmp_path):
    holder = {}
    captured = {}

    def on_convert(request):
        holder["repl"]._on_sigint(None, None)  # as the SIGINT handler would
        return ConversionResult(success=False, cancelled=True)

    factory, services = _builder(on_convert=on_convert)
    session = _ready_session(tmp_path)
    repl = Repl(
        session=session,
        deps=_deps(),
        io=FakeIO(lines=["/convert", "/exit"]),
        service_factory=factory,
    )
    holder["repl"] = repl
    assert repl.run() == 0
    assert "cancelling" in repl.io.text
    assert "cancelled" in repl.io.text
    assert repl._active_token is None  # cleared after dispatch
    assert session.pdf_path is not None and session.output_path is not None


def test_terminal_event_clears_the_active_token(tmp_path):
    holder = {}

    def on_convert(request):
        holder["repl"]._on_event(
            PipelineEvent(type="completed", phase=7, total_pages=1)
        )
        assert holder["repl"]._active_token is None  # closed the window
        return ConversionResult(success=True)

    factory, _ = _builder(on_convert=on_convert)
    repl = Repl(
        session=_ready_session(tmp_path),
        deps=_deps(),
        io=FakeIO(lines=["/convert", "/exit"]),
        service_factory=factory,
    )
    holder["repl"] = repl
    assert repl.run() == 0


def test_active_token_is_cleared_when_the_factory_raises(tmp_path):
    def factory(token, event_cb, deps):
        raise RuntimeError("boom")

    repl = Repl(
        session=_ready_session(tmp_path),
        deps=_deps(),
        io=FakeIO(lines=["/convert", "/exit"]),
        service_factory=factory,
    )
    assert repl.run() == 0
    assert repl._active_token is None  # finally cleared, no stale state
    assert "command failed" in repl.io.text


def test_active_token_is_cleared_when_convert_raises(tmp_path):
    def factory(token, event_cb, deps):
        service = FakeService()

        def convert(request, *, explicit_secret=None):
            raise RuntimeError("kaboom")

        service.convert = convert
        return service

    repl = Repl(
        session=_ready_session(tmp_path),
        deps=_deps(),
        io=FakeIO(lines=["/convert", "/exit"]),
        service_factory=factory,
    )
    assert repl.run() == 0
    assert repl._active_token is None
    assert "command failed" in repl.io.text


# -- rendering ---------------------------------------------------------------

def _renderer(lines=()):
    return Repl(session=Session(), deps=_deps(), io=FakeIO(lines=list(lines)))


def test_renderer_renders_phase_batch_validation_repair():
    repl = _renderer()
    repl._on_event(PipelineEvent(type="phase_started", phase=3, message="triage", total_pages=10))
    repl._on_event(PipelineEvent(type="tier2_batch_started", phase=4, metadata={"count": 4}))
    repl._on_event(PipelineEvent(type="validation_started", phase=7))
    repl._on_event(PipelineEvent(type="repair_started", phase=7, metadata={"attempt": 2}))
    assert "  [3] triage" in repl.io.text
    assert "model batch: 4 page(s)" in repl.io.text
    assert "validating..." in repl.io.text
    assert "repair pass 2" in repl.io.text


def test_page_progress_throttling_small_document_is_every_page():
    repl = _renderer()
    for index in range(7):
        repl._on_event(
            PipelineEvent(type="page_progress", phase=4, page_index=index, total_pages=7)
        )
    lines = [line for line in repl.io.written if line.startswith("  ... ")]
    assert len(lines) == 7  # step = max(1, 7 // 10) = 1


def test_page_progress_throttling_large_document_is_ten_steps():
    repl = _renderer()
    for index in range(500):
        repl._on_event(
            PipelineEvent(type="page_progress", phase=4, page_index=index, total_pages=500)
        )
    lines = [line for line in repl.io.written if line.startswith("  ... ")]
    assert len(lines) == 10  # 50, 100, ..., 500
    assert lines[-1] == "  ... 500/500"


def test_terminal_events_render_nothing():
    repl = _renderer()
    repl._on_event(PipelineEvent(type="completed", phase=7))
    repl._on_event(PipelineEvent(type="failed", phase=7))
    repl._on_event(PipelineEvent(type="cancelled", phase=0))
    assert repl.io.written == []


# -- onboarding --------------------------------------------------------------

def test_onboarding_runs_only_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(interactive, "show_onboarding", lambda *a: calls.append(1))
    Repl(
        session=Session(), deps=_deps(), io=FakeIO(lines=["/exit"]), onboarding=True
    ).run()
    assert calls == [1]
    Repl(
        session=Session(), deps=_deps(), io=FakeIO(lines=["/exit"]), onboarding=False
    ).run()
    assert calls == [1]  # unchanged: piped sessions never onboard


def test_onboarding_exceptions_never_block_the_session(monkeypatch):
    def boom(*args):
        raise RuntimeError("onboarding broken")

    monkeypatch.setattr(interactive, "show_onboarding", boom)
    repl = Repl(
        session=Session(), deps=_deps(), io=FakeIO(lines=["/exit"]), onboarding=True
    )
    assert repl.run() == 0
