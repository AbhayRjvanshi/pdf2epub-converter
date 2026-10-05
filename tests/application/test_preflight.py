"""Phase 7 (application): Level 2 preflight - routes, capability-checks."""

from pdf2epub.application.models import ConversionRequest
from pdf2epub.application.preflight import preflight
from pdf2epub.providers.models import ModelCapabilities, ModelDefinition
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import build_registry

_SYNTH = ProviderProfile(
    provider_id="synth",
    display_name="Synth",
    api_style="openai",
    credential_env_var="SYNTH_API_KEY",
    models=(
        ModelDefinition(
            "synth",
            "text-only",
            "Text Only",
            ModelCapabilities(structured_output=True),
        ),
        ModelDefinition(
            "synth",
            "hybrid",
            "Hybrid",
            ModelCapabilities(image_input=True, structured_output=True),
        ),
    ),
)
REGISTRY = build_registry([_SYNTH])


def make_request(pdf, tmp_path, provider_id="synth", model="hybrid"):
    return ConversionRequest(
        pdf_path=pdf,
        output_path=tmp_path / "out.epub",
        provider_id=provider_id,
        conversion_model=model,
    )


def test_digest_only_document_accepts_text_only_model(fixture_pdfs, tmp_path):
    request = make_request(
        fixture_pdfs["two_column"], tmp_path, model="text-only"
    )
    result = preflight(request, registry=REGISTRY)
    assert result.ok
    assert "vision" not in result.required_routes


def test_vision_document_rejects_text_only_model(fixture_pdfs, tmp_path):
    request = make_request(fixture_pdfs["scanned"], tmp_path, model="text-only")
    result = preflight(request, registry=REGISTRY)
    assert not result.ok
    assert any("vision" in p for p in result.problems)


def test_vision_document_accepts_hybrid_model(fixture_pdfs, tmp_path):
    request = make_request(fixture_pdfs["scanned"], tmp_path, model="hybrid")
    result = preflight(request, registry=REGISTRY)
    assert result.ok
    assert result.required_routes == frozenset({"vision"})


def test_offline_preflight_skips_capability_check(fixture_pdfs, tmp_path):
    request = make_request(
        fixture_pdfs["scanned"], tmp_path, provider_id="none", model=None
    )
    result = preflight(request, registry=REGISTRY)
    assert result.ok
    assert result.required_routes == frozenset()
    assert result.routing_summary["tier2_vision"] == 1
    assert result.bypassed_vision == 1  # offline embeds the raster


def test_preflight_builds_no_payloads(fixture_pdfs, tmp_path):
    request = make_request(fixture_pdfs["scanned"], tmp_path, model="hybrid")
    result = preflight(request, registry=REGISTRY)
    assert result.reports
    for report in result.reports:
        assert report.raster_bytes is None
        assert report.layout_digest is None


def test_corrupt_pdf_is_reported(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is definitely not a PDF file")
    request = make_request(bad, tmp_path)
    result = preflight(request, registry=REGISTRY)
    assert not result.ok
    assert any("cannot open PDF" in p for p in result.problems)


def test_cost_advisory_reports_tier2_counts(fixture_pdfs, tmp_path):
    request = make_request(fixture_pdfs["two_column"], tmp_path)
    result = preflight(request, registry=REGISTRY)
    assert "digest" in result.cost_advisory
    assert result.routing_summary["tier2_digest"] >= 1
