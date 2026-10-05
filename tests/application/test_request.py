"""Phase 7 (application): Level 1 request validation - never opens the PDF."""

from pdf2epub.application.models import ConversionOptions, ConversionRequest
from pdf2epub.application.request import validate_request
from pdf2epub.providers.models import ModelDefinition
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import build_registry

REGISTRY = build_registry()

_SYNTH = ProviderProfile(
    provider_id="synth",
    display_name="Synth",
    api_style="openai",
    credential_env_var="SYNTH_API_KEY",
    models=(
        ModelDefinition("synth", "old-model", "Old", status="retired"),
        ModelDefinition("synth", "current-model", "Current"),
    ),
)
SYNTH_REGISTRY = build_registry([_SYNTH])


def make_request(tmp_path, **kw):
    pdf = kw.pop("pdf_path", None)
    if pdf is None:
        pdf = tmp_path / "book.pdf"
        pdf.write_bytes(b"%PDF-1.4 dummy")
    options = kw.pop("options", ConversionOptions())
    return ConversionRequest(
        pdf_path=pdf,
        output_path=kw.pop("output_path", tmp_path / "out.epub"),
        options=options,
        **kw,
    )


def test_missing_pdf_is_an_input_error(tmp_path):
    request = make_request(tmp_path, pdf_path=tmp_path / "nope.pdf")
    assessment = validate_request(request, registry=REGISTRY)
    assert not assessment.ok
    assert any("input not found" in e for e in assessment.input_errors)


def test_pdf_directory_is_an_input_error(tmp_path):
    request = make_request(tmp_path, pdf_path=tmp_path)
    assessment = validate_request(request, registry=REGISTRY)
    assert any("not a file" in e for e in assessment.input_errors)


def test_output_directory_is_an_input_error(tmp_path):
    request = make_request(tmp_path, output_path=tmp_path)
    assessment = validate_request(request, registry=REGISTRY)
    assert any("is a directory" in e for e in assessment.input_errors)


def test_existing_output_requires_overwrite(tmp_path):
    out = tmp_path / "out.epub"
    out.write_bytes(b"existing")
    blocked = validate_request(
        make_request(tmp_path, output_path=out), registry=REGISTRY
    )
    assert any("already exists" in e for e in blocked.input_errors)

    allowed = validate_request(
        make_request(
            tmp_path, output_path=out, options=ConversionOptions(overwrite=True)
        ),
        registry=REGISTRY,
    )
    assert allowed.ok


def test_output_parent_is_created(tmp_path):
    out = tmp_path / "nested" / "deep" / "out.epub"
    assessment = validate_request(
        make_request(tmp_path, output_path=out), registry=REGISTRY
    )
    assert assessment.ok
    assert out.parent.is_dir()


def test_unknown_provider_is_a_config_error(tmp_path):
    request = make_request(tmp_path, provider_id="martian")
    assessment = validate_request(request, registry=REGISTRY)
    assert any("unknown provider" in e for e in assessment.config_errors)


def test_named_provider_without_credential_is_a_config_error(tmp_path):
    request = make_request(
        tmp_path, provider_id="openai", conversion_model="gpt-4o"
    )
    assessment = validate_request(request, registry=REGISTRY, environ={})
    assert not assessment.ok
    assert any("OPENAI_API_KEY" in e for e in assessment.config_errors)


def test_named_provider_with_credential_and_model_is_ok(tmp_path):
    request = make_request(
        tmp_path, provider_id="openai", conversion_model="gpt-4o"
    )
    assessment = validate_request(
        request, registry=REGISTRY, environ={"OPENAI_API_KEY": "sk-test"}
    )
    assert assessment.ok
    assert assessment.credential is not None
    assert assessment.credential.source == "environment"


def test_named_provider_requires_a_model(tmp_path):
    request = make_request(tmp_path, provider_id="openai", conversion_model=None)
    assessment = validate_request(
        request, registry=REGISTRY, environ={"OPENAI_API_KEY": "sk-test"}
    )
    assert any("requires a conversion_model" in e for e in assessment.config_errors)


def test_offline_provider_accepts_no_model(tmp_path):
    request = make_request(tmp_path, provider_id="none", conversion_model=None)
    assessment = validate_request(request, registry=REGISTRY, environ={})
    assert assessment.ok
    assert assessment.credential is None


def test_model_set_for_offline_provider_warns(tmp_path):
    request = make_request(tmp_path, provider_id="none", conversion_model="gpt-4o")
    assessment = validate_request(request, registry=REGISTRY, environ={})
    assert assessment.ok
    assert any("ignored for the offline provider" in w for w in assessment.warnings)


def test_scalar_bounds_are_config_errors(tmp_path):
    options = ConversionOptions(
        batch_size=0, max_repair_attempts=-1, font_sample_pages=0
    )
    assessment = validate_request(
        make_request(tmp_path, options=options), registry=REGISTRY, environ={}
    )
    assert len(assessment.config_errors) == 3


def test_unknown_model_is_advisory_not_fatal(tmp_path):
    request = make_request(
        tmp_path, provider_id="openai", conversion_model="brand-new-x"
    )
    assessment = validate_request(
        request, registry=REGISTRY, environ={"OPENAI_API_KEY": "sk-test"}
    )
    assert assessment.ok
    assert any("not in" in w for w in assessment.warnings)


def test_retired_model_warns(tmp_path):
    request = make_request(
        tmp_path, provider_id="synth", conversion_model="old-model"
    )
    assessment = validate_request(
        request, registry=SYNTH_REGISTRY, environ={"SYNTH_API_KEY": "k"}
    )
    assert assessment.ok
    assert any("retired" in w for w in assessment.warnings)


def test_request_coerces_strings_to_paths(tmp_path):
    request = ConversionRequest(
        pdf_path=str(tmp_path / "b.pdf"), output_path=str(tmp_path / "o.epub")
    )
    assert request.pdf_path == tmp_path / "b.pdf"
    assert isinstance(request.output_path, type(tmp_path / "o.epub"))


def test_ok_property_reflects_errors(tmp_path):
    good = validate_request(
        make_request(tmp_path, pdf_path=tmp_path / "missing.pdf"),
        registry=REGISTRY,
        environ={},
    )
    assert good.ok is False  # missing pdf
