"""Phase 12: the interactive command layer with scripted IO.

No TTY anywhere: every prompt is scripted, the service is faked except
for one real offline end-to-end run, and secret hygiene is string-scanned.
"""

from pathlib import Path

import fitz
import pytest

import pdf2epub.application.commands as commands
from pdf2epub.application import ConversionResult, PreflightResult, dispatch
from pdf2epub.application.commands import SessionDeps
from pdf2epub.application.session import Session
from pdf2epub.config import AppConfig
from pdf2epub.providers.registry import build_registry


class ScriptedIO:
    def __init__(self, lines=(), secrets=()):
        self._lines = list(lines)
        self._secrets = list(secrets)
        self.output = []
        self.prompts = []
        self.secret_prompts = []

    def read_line(self, prompt):
        self.prompts.append(prompt)
        return self._lines.pop(0) if self._lines else ""

    def read_secret(self, prompt):
        self.secret_prompts.append(prompt)
        return self._secrets.pop(0) if self._secrets else ""

    def write(self, text):
        self.output.append(text)

    @property
    def text(self):
        return "\n".join(self.output)


class FakeConfigManager:
    def __init__(self, config=None):
        self._config = config or AppConfig()
        self.saved = []
        self._path = Path("config.toml")

    def load(self):
        return self._config

    def save(self, updates):
        self.saved.append(updates)
        return self._config

    def path(self):
        return self._path


class FakeService:
    def __init__(self, result=None):
        self.result = result or ConversionResult(
            success=True, output_path=Path("out.epub")
        )
        self.requests = []
        self.secrets = []

    def convert(self, request, *, explicit_secret=None):
        self.requests.append(request)
        self.secrets.append(explicit_secret)
        return self.result


def make_pdf(tmp_path, name="book.pdf"):
    path = tmp_path / name
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def make_deps(service=None, config=None, environ=None):
    service = service if service is not None else FakeService()
    deps = SessionDeps(
        registry=build_registry(),
        config_manager=FakeConfigManager(config),
        service_factory=lambda: service,
        environ=environ if environ is not None else {},
    )
    return deps, service


def _preflight(routes=("digest",)):
    return PreflightResult(
        total_pages=1,
        routing_summary={"tier1": 0, "tier2_digest": 1, "tier2_vision": 0},
        required_routes=frozenset(routes),
        bypassed_vision=0,
    )


# -- dispatch basics ---------------------------------------------------------

def test_empty_line_is_a_noop():
    io = ScriptedIO()
    result = dispatch("", session=Session(), io=io, deps=make_deps()[0])
    assert result.output == "" and not result.failed and not result.exit


def test_unknown_command_is_honest():
    result = dispatch("/nope", session=Session(), io=ScriptedIO(), deps=make_deps()[0])
    assert result.failed
    assert "unknown command" in result.output


def test_help_lists_the_commands():
    result = dispatch("/help", session=Session(), io=ScriptedIO(), deps=make_deps()[0])
    for verb in ("select", "export", "provider", "model", "convert", "status", "exit"):
        assert f"/{verb}" in result.output


def test_exit_sets_the_exit_flag():
    result = dispatch("/exit", session=Session(), io=ScriptedIO(), deps=make_deps()[0])
    assert result.exit and result.output == "bye"


def test_dispatch_never_raises_from_a_handler_bug(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path)
    monkeypatch.setattr(
        commands, "_read_metadata", lambda path: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = dispatch(
        "/select", session=Session(),
        io=ScriptedIO(lines=[str(pdf), "", ""]),
        deps=make_deps()[0],
    )
    assert result.failed
    assert "command failed" in result.output


# -- /select -----------------------------------------------------------------

def test_select_happy_path_sets_pdf_title_author_and_output(tmp_path):
    pdf = make_pdf(tmp_path)
    io = ScriptedIO(lines=[str(pdf), "My Book", "Jane Doe"])
    session = Session()
    result = dispatch("/select", session=session, io=io, deps=make_deps()[0])
    assert not result.failed
    assert session.pdf_path == pdf
    assert session.title == "My Book"
    assert session.author == "Jane Doe"
    assert session.output_path == Path("book.epub")  # auto-derived


def test_select_missing_pdf_leaves_state_unchanged():
    io = ScriptedIO(lines=["nowhere.pdf", "", ""])
    session = Session()
    result = dispatch("/select", session=session, io=io, deps=make_deps()[0])
    assert result.failed
    assert session.pdf_path is None


def test_select_empty_title_falls_back_to_metadata(tmp_path):
    pdf = make_pdf(tmp_path)
    io = ScriptedIO(lines=[str(pdf), "", ""])
    session = Session()
    dispatch("/select", session=session, io=io, deps=make_deps()[0])
    assert session.title is None and session.author is None


def test_select_prompt_shows_the_pdf_metadata(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path)
    monkeypatch.setattr(commands, "_read_metadata", lambda path: ("Meta Title", "A. Author"))
    io = ScriptedIO(lines=[str(pdf), "", ""])
    dispatch("/select", session=Session(), io=io, deps=make_deps()[0])
    assert "Meta Title" in io.prompts[1]
    assert "A. Author" in io.prompts[2]


# -- /export -----------------------------------------------------------------

def test_export_sets_the_output(tmp_path):
    io = ScriptedIO(lines=[str(tmp_path / "o.epub")])
    session = Session()
    result = dispatch("/export", session=session, io=io, deps=make_deps()[0])
    assert not result.failed
    assert session.output_path == tmp_path / "o.epub"
    assert session.output_auto is False


def test_export_existing_overwrite_yes(tmp_path):
    out = tmp_path / "o.epub"
    out.write_bytes(b"existing")
    io = ScriptedIO(lines=[str(out), "y"])
    session = Session()
    dispatch("/export", session=session, io=io, deps=make_deps()[0])
    assert session.overwrite is True


def test_export_existing_overwrite_no(tmp_path):
    out = tmp_path / "o.epub"
    out.write_bytes(b"existing")
    io = ScriptedIO(lines=[str(out), "n"])
    session = Session()
    result = dispatch("/export", session=session, io=io, deps=make_deps()[0])
    assert result.failed
    assert session.overwrite is False
    assert "refuse" in result.output


def test_export_creates_missing_parents(tmp_path):
    out = tmp_path / "nested" / "deep" / "o.epub"
    io = ScriptedIO(lines=[str(out)])
    session = Session()
    dispatch("/export", session=session, io=io, deps=make_deps()[0])
    assert out.parent.is_dir()


def test_export_rejects_a_directory(tmp_path):
    io = ScriptedIO(lines=[str(tmp_path)])
    result = dispatch("/export", session=Session(), io=io, deps=make_deps()[0])
    assert result.failed
    assert "is a directory" in result.output


def test_export_rejects_an_uncreatable_parent(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a directory")
    io = ScriptedIO(lines=[str(blocker / "o.epub")])
    result = dispatch("/export", session=Session(), io=io, deps=make_deps()[0])
    assert result.failed


# -- /provider ---------------------------------------------------------------

def test_provider_selects_offline():
    io = ScriptedIO(lines=["1"])
    session = Session()
    result = dispatch("/provider", session=session, io=io, deps=make_deps()[0])
    assert not result.failed
    assert session.provider_id == "none"


def test_provider_uses_an_environment_credential():
    io = ScriptedIO(lines=["2", "n", "n"])  # openai, no verify, no save
    session = Session()
    deps, _ = make_deps(environ={"OPENAI_API_KEY": "sk-env"})
    result = dispatch("/provider", session=session, io=io, deps=deps)
    assert not result.failed
    assert session.provider_id == "openai"
    assert session.credential.source == "environment"
    assert "Using credential from environment" in io.text


def test_provider_manual_secret_keyring_and_save():
    stored = []

    io = ScriptedIO(lines=["2", "n", "y", "y"], secrets=["sk-manual"])
    session = Session()
    deps, _ = make_deps(environ={})
    monkeypatch_store = lambda provider, secret: stored.append((provider, secret)) or True

    original = commands.keyring_store
    commands.keyring_store = monkeypatch_store
    try:
        result = dispatch("/provider", session=session, io=io, deps=deps)
    finally:
        commands.keyring_store = original

    assert not result.failed
    assert session.explicit_secret == "sk-manual"
    assert session.credential.source == "explicit"
    assert stored == [("openai", "sk-manual")]
    assert deps.config_manager.saved == [{"provider": {"name": "openai"}}]
    assert "sk-manual" not in io.text  # secret never reaches output


def test_provider_change_clears_the_manual_secret():
    io = ScriptedIO(lines=["2", "n", "n", "n", "1"], secrets=["sk-manual"])
    session = Session()
    deps, _ = make_deps(environ={})

    dispatch("/provider", session=session, io=io, deps=deps)
    assert session.explicit_secret == "sk-manual"
    dispatch("/provider", session=session, io=io, deps=deps)  # -> none
    assert session.provider_id == "none"
    assert session.explicit_secret is None


def test_provider_verification_is_invoked_when_requested():
    registry = build_registry()
    adapter = registry.get("openai")
    calls = []
    monkeypatch_verify = lambda credential: calls.append(credential) or True

    original = adapter.validate_credentials
    adapter.validate_credentials = monkeypatch_verify
    try:
        io = ScriptedIO(lines=["2", "y", "n"])
        session = Session()
        deps = SessionDeps(
            registry=registry,
            config_manager=FakeConfigManager(),
            service_factory=lambda: FakeService(),
            environ={"OPENAI_API_KEY": "sk-env"},
        )
        result = dispatch("/provider", session=session, io=io, deps=deps)
    finally:
        adapter.validate_credentials = original

    assert calls == ["sk-env"]
    assert "Credentials verified." in io.text
    assert not result.failed


def test_provider_unknown_selection_fails_cleanly():
    io = ScriptedIO(lines=["martian"])
    result = dispatch("/provider", session=Session(), io=io, deps=make_deps()[0])
    assert result.failed


# -- /model ------------------------------------------------------------------

def test_model_selects_from_the_list():
    session = Session()
    session.select_provider("openai")
    io = ScriptedIO(lines=["1"])
    result = dispatch("/model", session=session, io=io, deps=make_deps()[0])
    assert not result.failed
    assert session.conversion_model == "gpt-4o"


def test_model_allows_custom_ids_with_a_warning():
    session = Session()
    session.select_provider("openai")
    io = ScriptedIO(lines=["totally-custom-model"])
    result = dispatch("/model", session=session, io=io, deps=make_deps()[0])
    assert session.conversion_model == "totally-custom-model"
    assert "not in" in result.output


def test_model_requires_a_provider_first():
    result = dispatch("/model", session=Session(), io=ScriptedIO(lines=["1"]),
                       deps=make_deps()[0])
    assert result.failed
    assert "choose a provider" in result.output


# -- /status and /config -----------------------------------------------------

def test_status_shows_fields_and_readiness(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "book.pdf", title="T", author=None, output_dir=".")
    session.select_provider("none")
    result = dispatch("/status", session=session, io=ScriptedIO(), deps=make_deps()[0])
    assert "book.pdf" in result.output
    assert "none" in result.output
    assert "READY" in result.output


def test_config_shows_saved_configuration():
    deps, _ = make_deps(config=AppConfig(provider_name="anthropic"))
    result = dispatch("/config", session=Session(), io=ScriptedIO(), deps=deps)
    assert "anthropic" in result.output


# -- /convert ----------------------------------------------------------------

def test_convert_not_ready_never_touches_the_service():
    deps, service = make_deps()
    result = dispatch("/convert", session=Session(), io=ScriptedIO(), deps=deps)
    assert result.failed
    assert "not ready" in result.output
    assert service.requests == []


def test_convert_ready_sends_the_exact_request(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "book.pdf", title="T", author="A", output_dir=".")
    session.set_output(tmp_path / "out.epub", overwrite=True)
    session.select_provider("none")

    pre = _preflight()
    service = FakeService(
        result=ConversionResult(success=True, output_path=tmp_path / "out.epub",
                                 preflight=pre)
    )
    deps = SessionDeps(
        registry=build_registry(),
        config_manager=FakeConfigManager(),
        service_factory=lambda: service,
        environ={},
    )
    io = ScriptedIO()
    result = dispatch("/convert", session=session, io=io, deps=deps)
    assert not result.failed
    assert "done" in result.output

    request = service.requests[0]
    assert request.pdf_path == tmp_path / "book.pdf"
    assert request.output_path == tmp_path / "out.epub"
    assert request.title == "T" and request.author == "A"
    assert request.provider_id == "none"
    assert request.options.overwrite is True
    assert session.last_routing is pre  # routing plan updated from the result


def test_convert_passes_the_session_secret_once(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "book.pdf", title=None, author=None, output_dir=".")
    session.select_provider("openai")
    session.set_explicit_secret("sk-manual")
    session.refresh_credential(build_registry(), environ={})
    session.select_model("gpt-4o")

    deps, service = make_deps()
    io = ScriptedIO()
    result = dispatch("/convert", session=session, io=io, deps=deps)
    assert service.secrets == ["sk-manual"]
    assert "sk-manual" not in io.text  # secret hygiene across all output


def test_real_offline_convert_end_to_end(fixture_pdfs, tmp_path):
    from pdf2epub.application import ConversionService

    session = Session()
    session.select_pdf(fixture_pdfs["single_column"], title=None, author=None)
    session.set_output(tmp_path / "out.epub")
    session.select_provider("none")

    config = AppConfig(cache_dir=str(tmp_path / "cache"))
    deps = SessionDeps(
        registry=build_registry(),
        config_manager=FakeConfigManager(config),
        service_factory=lambda: ConversionService(
            registry=build_registry(), config=config, environ={}
        ),
        environ={},
    )
    result = dispatch("/convert", session=session, io=ScriptedIO(), deps=deps)
    assert not result.failed
    assert (tmp_path / "out.epub").exists()
    assert session.last_routing is not None
