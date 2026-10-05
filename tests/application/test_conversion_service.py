"""Phase 9: the ConversionService - one typed door to the engine.

Recorder-based tests pin every parameter crossing the seam; two real
(offline and mock-provider) conversions prove the engine actually runs.
"""

import pytest

from pdf2epub.application import (
    ConversionOptions,
    ConversionRequest,
    ConversionResult,
    ConversionService,
)
from pdf2epub.config import AppConfig, paths
from pdf2epub.engine import confidence_router, driver
from pdf2epub.engine.cancellation import CancellationToken
from pdf2epub.providers.errors import ProviderUnavailableError
from pdf2epub.providers.mock import MockProvider
from pdf2epub.providers.models import ModelCapabilities, ModelDefinition
from pdf2epub.providers.offline import OfflineProvider
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import Registry, build_registry

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


def _registry_with_mock():
    registry = Registry()
    registry.register(OfflineProvider())
    registry.register(MockProvider())
    return registry


def _pdf(tmp_path, name="book.pdf"):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 dummy")
    return path


def _request(pdf, tmp_path, *, provider="none", model=None, options=None, out="out.epub"):
    return ConversionRequest(
        pdf_path=pdf,
        output_path=tmp_path / out,
        provider_id=provider,
        conversion_model=model,
        options=options or ConversionOptions(),
    )


class _FakeBuild:
    chapters = [1, 2, 3, 4]


def _record_pipeline(monkeypatch):
    calls = []

    def fake_run_pipeline(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "build": _FakeBuild(),
            "routing": {"tier1": 1, "tier2_digest": 0, "tier2_vision": 0},
        }

    monkeypatch.setattr(driver, "run_pipeline", fake_run_pipeline)
    return calls


# -- real conversions -------------------------------------------------------

def test_offline_conversion_produces_a_complete_result(fixture_pdfs, tmp_path):
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(_request(fixture_pdfs["clean_book"], tmp_path))
    assert result.success
    assert result.output_path == tmp_path / "out.epub"
    assert result.output_path.exists()
    assert result.chapter_count >= 1
    assert result.raw is not None
    assert result.validation_report is not None
    assert result.preflight is not None
    assert result.exit_code == 0


def test_mock_provider_drives_the_real_engine(fixture_pdfs, tmp_path):
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(
        _request(
            fixture_pdfs["two_column"], tmp_path,
            provider="mock", model="mock-model",
            options=ConversionOptions(skip_validation=True),
        )
    )
    assert result.success
    assert (tmp_path / "out.epub").exists()


def test_routing_runs_exactly_once(fixture_pdfs, tmp_path, monkeypatch):
    calls = {"n": 0}
    real = confidence_router.route_document

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(confidence_router, "route_document", counting)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(
        _request(
            fixture_pdfs["clean_book"], tmp_path,
            options=ConversionOptions(skip_validation=True),
        )
    )
    assert result.success
    assert calls["n"] == 1  # preflight only; the engine used precomputed reports


def test_events_are_forwarded_and_collected(fixture_pdfs, tmp_path):
    seen = []
    service = ConversionService(
        registry=_registry_with_mock(), environ={}, event_cb=seen.append
    )
    result = service.convert(
        _request(
            fixture_pdfs["clean_book"], tmp_path,
            options=ConversionOptions(skip_validation=True),
        )
    )
    assert result.events
    assert seen == result.events


# -- parameter mapping (recorder) -------------------------------------------

def test_offline_conversion_never_creates_a_client(fixture_pdfs, tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    service.convert(_request(fixture_pdfs["clean_book"], tmp_path))
    assert calls and calls[0]["llm_adapter"] is None


def test_pipeline_receives_the_mapped_options(fixture_pdfs, tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    config = AppConfig(ace_enabled=False, cache_dir=str(tmp_path / "cfgcache"))
    service = ConversionService(
        registry=_registry_with_mock(), config=config, environ={}
    )
    options = ConversionOptions(
        batch_size=7, max_repair_attempts=3, font_sample_pages=9,
        spool_images=False, quiet=True,
    )
    service.convert(_request(fixture_pdfs["clean_book"], tmp_path, options=options))
    kw = calls[0]
    assert kw["batch_size"] == 7
    assert kw["max_repair_attempts"] == 3
    assert kw["font_sample_pages"] == 9
    assert kw["spool_images"] is False
    assert kw["verbose"] is False
    assert kw["validators"] == ("epubcheck",)
    assert kw["cache_dir"] == str(tmp_path / "cfgcache")
    assert kw["precomputed_reports"] is not None
    assert kw["cancel_token"] is None


def test_default_config_maps_to_engine_default_validators(fixture_pdfs, tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    service.convert(_request(fixture_pdfs["clean_book"], tmp_path))
    assert calls[0]["validators"] is None  # both enabled -> engine default


def test_both_validators_disabled_maps_to_the_empty_tuple(fixture_pdfs, tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    config = AppConfig(epubcheck_enabled=False, ace_enabled=False)
    service = ConversionService(
        registry=_registry_with_mock(), config=config, environ={}
    )
    service.convert(_request(fixture_pdfs["clean_book"], tmp_path))
    assert calls[0]["validators"] == ()


def test_explicit_cache_dir_beats_config(fixture_pdfs, tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    config = AppConfig(cache_dir=str(tmp_path / "cfgcache"))
    service = ConversionService(
        registry=_registry_with_mock(), config=config, environ={}
    )
    options = ConversionOptions(cache_dir=str(tmp_path / "explicit"))
    service.convert(_request(fixture_pdfs["clean_book"], tmp_path, options=options))
    assert calls[0]["cache_dir"] == str(tmp_path / "explicit")


def test_default_cache_dir_is_the_platform_cache(fixture_pdfs, tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    service.convert(_request(fixture_pdfs["clean_book"], tmp_path))
    assert calls[0]["cache_dir"] == str(paths.cache_dir())


# -- failure paths -----------------------------------------------------------

def test_input_error_short_circuits_everything(tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(_request(tmp_path / "missing.pdf", tmp_path))
    assert not result.success
    assert result.input_errors
    assert result.exit_code == 2
    assert calls == []


def test_unknown_provider_is_a_config_error(tmp_path, monkeypatch):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(
        _request(_pdf(tmp_path), tmp_path, provider="martian", model="x")
    )
    assert not result.success
    assert result.config_errors
    assert result.exit_code == 1
    assert calls == []


def test_missing_credential_is_a_config_error(tmp_path):
    service = ConversionService(registry=build_registry(), environ={})
    result = service.convert(
        _request(_pdf(tmp_path), tmp_path, provider="openai", model="gpt-4o")
    )
    assert not result.success
    assert any("OPENAI_API_KEY" in e for e in result.config_errors)
    assert result.exit_code == 1


def test_capability_mismatch_is_rejected_before_spending(
    fixture_pdfs, tmp_path, monkeypatch
):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(
        registry=build_registry([_SYNTH]), environ={"SYNTH_API_KEY": "k"}
    )
    result = service.convert(
        _request(
            fixture_pdfs["scanned"], tmp_path,
            provider="synth", model="text-only",
        )
    )
    assert not result.success
    assert any("vision" in e for e in result.config_errors)
    assert calls == []


def test_provider_error_becomes_a_structured_error(
    fixture_pdfs, tmp_path, monkeypatch
):
    registry = build_registry([_SYNTH])
    adapter = registry.get("synth")

    def boom(model_id, credential):
        raise ProviderUnavailableError("pip install 'pdf2epub[openai]'")

    monkeypatch.setattr(adapter, "create_llm_callable", boom)
    service = ConversionService(registry=registry, environ={"SYNTH_API_KEY": "k"})
    result = service.convert(
        _request(
            fixture_pdfs["two_column"], tmp_path,
            provider="synth", model="text-only",
        )
    )
    assert not result.success
    assert result.error and "pip install" in result.error
    assert result.exit_code == 1


def test_cancelled_token_returns_a_clean_result(fixture_pdfs, tmp_path):
    token = CancellationToken()
    token.cancel()
    service = ConversionService(
        registry=_registry_with_mock(), environ={}, cancel_token=token
    )
    result = service.convert(_request(fixture_pdfs["clean_book"], tmp_path))
    assert result.cancelled and not result.success
    assert result.exit_code == 130
    assert result.output_path is None


# -- report-only dry runs ----------------------------------------------------

def test_report_only_returns_routing_without_running_the_engine(
    fixture_pdfs, tmp_path, monkeypatch
):
    calls = _record_pipeline(monkeypatch)
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(
        _request(
            fixture_pdfs["two_column"], tmp_path, out="never.epub",
            options=ConversionOptions(report_only=True),
        )
    )
    assert result.success and result.report_only
    assert result.preflight is not None
    assert result.preflight.routing_summary["tier2_digest"] >= 1
    assert calls == []
    assert not (tmp_path / "never.epub").exists()


def test_report_only_demotes_capability_problems_to_warnings(
    fixture_pdfs, tmp_path
):
    service = ConversionService(registry=build_registry([_SYNTH]), environ={})
    result = service.convert(
        _request(
            fixture_pdfs["scanned"], tmp_path,
            provider="synth", model="text-only",
            options=ConversionOptions(report_only=True),
        )
    )
    assert result.success  # dry run cannot spend, so mismatches are advisory
    assert result.preflight.problems
    assert any("vision" in w for w in result.warnings)


def test_report_only_read_failure_is_an_input_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    service = ConversionService(registry=_registry_with_mock(), environ={})
    result = service.convert(
        _request(bad, tmp_path, options=ConversionOptions(report_only=True))
    )
    assert not result.success
    assert result.input_errors
    assert result.exit_code == 2


# -- result semantics --------------------------------------------------------

def test_all_errors_aggregates_every_bucket():
    result = ConversionResult(
        success=False, input_errors=["a"], config_errors=["b"], error="c"
    )
    assert result.all_errors == ["a", "b", "c"]


def test_exit_code_mapping():
    assert ConversionResult(success=True).exit_code == 0
    assert ConversionResult(success=False, cancelled=True).exit_code == 130
    assert ConversionResult(success=False, input_errors=["x"]).exit_code == 2
    assert ConversionResult(success=False, config_errors=["x"]).exit_code == 1
