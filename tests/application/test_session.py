"""Phase 12: session state, invalidation rules and readiness."""

from pathlib import Path

import pytest

from pdf2epub.application.preflight import PreflightResult
from pdf2epub.application.session import Readiness, Session
from pdf2epub.config import AppConfig
from pdf2epub.providers.models import ModelCapabilities, ModelDefinition
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import build_registry

REGISTRY = build_registry()

_SYNTH = ProviderProfile(
    provider_id="synth",
    display_name="Synth",
    api_style="openai",
    credential_env_var="SYNTH_API_KEY",
    models=(
        ModelDefinition(
            "synth", "text-only", "Text Only",
            ModelCapabilities(structured_output=True),
        ),
        ModelDefinition(
            "synth", "hybrid", "Hybrid",
            ModelCapabilities(image_input=True, structured_output=True),
        ),
    ),
)
SYNTH_REGISTRY = build_registry([_SYNTH])


def _routing(*routes):
    return PreflightResult(
        total_pages=1,
        routing_summary={"tier1": 0, "tier2_digest": 1, "tier2_vision": 0},
        required_routes=frozenset(routes),
        bypassed_vision=0,
    )


def _offline_ready(tmp_path):
    session = Session()
    session.select_pdf(
        tmp_path / "book.pdf", title=None, author=None, output_dir="."
    )
    session.select_provider("none")
    return session


# -- initialization ---------------------------------------------------------

def test_from_config_seeds_provider_and_model():
    config = AppConfig(provider_name="openai", conversion_model="gpt-4o")
    session = Session.from_config(config)
    assert session.provider_id == "openai"
    assert session.conversion_model == "gpt-4o"


def test_fresh_session_is_not_ready_with_exact_gaps():
    report = Session().readiness(REGISTRY)
    assert report.state is Readiness.NOT_READY
    assert report.missing == [
        "PDF not selected (/select)",
        "output path not set (/export)",
        "provider not chosen (/provider)",
    ]


# -- invalidation rules -----------------------------------------------------

def test_select_pdf_derives_the_output_name():
    session = Session()
    session.select_pdf(Path("docs/book.pdf"), title=None, author=None, output_dir="out")
    assert session.output_path == Path("out") / "book.epub"
    assert session.output_auto is True


def test_select_pdf_rederives_auto_output_but_keeps_explicit():
    session = Session()
    session.select_pdf(Path("a.pdf"), title=None, author=None)
    session.set_output(Path("custom.epub"))
    session.select_pdf(Path("b.pdf"), title=None, author=None)
    assert session.output_path == Path("custom.epub")  # explicit /export wins
    # and a purely auto output follows the PDF name
    fresh = Session()
    fresh.select_pdf(Path("a.pdf"), title=None, author=None)
    fresh.select_pdf(Path("b.pdf"), title=None, author=None)
    assert fresh.output_path == Path("b.epub")


def test_select_pdf_drops_the_routing_plan():
    session = _offline_ready(Path("."))
    session.last_routing = _routing("digest")
    session.select_pdf(Path("other.pdf"), title=None, author=None)
    assert session.last_routing is None


def test_select_provider_clears_model_credential_secret_and_routing():
    session = Session()
    session.select_provider("openai")
    session.select_model("gpt-4o")
    session.set_explicit_secret("sk-manual-openai")
    session.refresh_credential(REGISTRY, environ={})
    session.last_routing = _routing("digest")

    session.select_provider("anthropic")

    assert session.conversion_model is None
    assert session.credential is None
    assert session.explicit_secret is None  # a key for one provider never crosses
    assert session.last_routing is None
    assert session.provider_id == "anthropic"


# -- credential resolution ---------------------------------------------------

def test_refresh_credential_resolves_from_environment():
    session = Session()
    session.select_provider("openai")
    session.refresh_credential(REGISTRY, environ={"OPENAI_API_KEY": "sk-env"})
    assert session.credential is not None
    assert session.credential.source == "environment"
    assert session.credential.credential == "sk-env"


def test_manual_explicit_secret_becomes_the_credential():
    session = Session()
    session.select_provider("openai")
    session.set_explicit_secret("sk-manual")
    result = session.refresh_credential(REGISTRY, environ={})
    assert result is not None
    assert result.source == "explicit"
    assert result.credential == "sk-manual"


def test_refresh_credential_skips_offline():
    session = Session()
    session.select_provider("none")
    assert session.refresh_credential(REGISTRY, environ={}) is None


# -- readiness ladder --------------------------------------------------------

def test_offline_session_is_ready(tmp_path):
    report = _offline_ready(tmp_path).readiness(REGISTRY)
    assert report.state is Readiness.READY
    assert report.missing == []


def test_online_without_credential_names_the_env_var(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "b.pdf", title=None, author=None)
    session.select_provider("openai")
    session.refresh_credential(REGISTRY, environ={})
    report = session.readiness(REGISTRY)
    assert report.state is Readiness.NOT_READY
    assert any("OPENAI_API_KEY" in g for g in report.missing)


def test_manual_secret_satisfies_credential_readiness(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "b.pdf", title=None, author=None)
    session.select_provider("openai")
    session.set_explicit_secret("sk-manual")
    session.refresh_credential(REGISTRY, environ={})
    session.select_model("gpt-4o")
    report = session.readiness(REGISTRY)
    # online + credential + model, routing unknown -> preflight still required
    assert report.state is Readiness.READY_WITH_PREFLIGHT_REQUIRED
    assert report.missing == []


def test_online_with_routing_and_compatible_model_is_ready(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "b.pdf", title=None, author=None)
    session.select_provider("openai")
    session.refresh_credential(REGISTRY, environ={"OPENAI_API_KEY": "sk-env"})
    session.select_model("gpt-4o")
    session.last_routing = _routing("digest", "vision")
    report = session.readiness(REGISTRY)
    assert report.state is Readiness.READY


def test_incompatible_model_is_a_readiness_gap(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "b.pdf", title=None, author=None)
    session.select_provider("synth")
    session.refresh_credential(SYNTH_REGISTRY, environ={"SYNTH_API_KEY": "k"})
    session.select_model("text-only")
    session.last_routing = _routing("vision")
    report = session.readiness(SYNTH_REGISTRY)
    assert report.state is Readiness.NOT_READY
    assert any("vision" in g for g in report.missing)


def test_missing_model_is_a_gap_when_online(tmp_path):
    session = Session()
    session.select_pdf(tmp_path / "b.pdf", title=None, author=None)
    session.select_provider("openai")
    session.refresh_credential(REGISTRY, environ={"OPENAI_API_KEY": "sk-env"})
    report = session.readiness(REGISTRY)
    assert report.state is Readiness.NOT_READY
    assert any("/model" in g for g in report.missing)


# -- build_request -----------------------------------------------------------

def test_build_request_maps_the_session(tmp_path):
    session = Session()
    session.select_pdf(
        tmp_path / "book.pdf", title="T", author="A", output_dir="."
    )
    session.set_output(tmp_path / "custom.epub", overwrite=True)
    session.select_provider("none")
    request = session.build_request()
    assert request.pdf_path == tmp_path / "book.pdf"
    assert request.output_path == tmp_path / "custom.epub"
    assert request.title == "T" and request.author == "A"
    assert request.provider_id == "none"
    assert request.options.overwrite is True
    assert request.options.cache_dir is None  # service layers config -> platform


def test_build_request_refuses_an_incomplete_session():
    with pytest.raises(ValueError):
        Session().build_request()
