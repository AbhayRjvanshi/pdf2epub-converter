"""Phase 4: route capabilities are model properties; the routes
themselves come from outside (Phase 7 preflight), never re-derived here."""

from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.mock import MockProvider
from pdf2epub.providers.models import ModelCapabilities, ModelDefinition
from pdf2epub.providers.requirements import (
    check_model_for_routes,
    resolve_model,
    supports_digest,
    supports_vision,
)

_OPENAI = next(p for p in PROFILES if p.provider_id == "openai")
_GPT4O = _OPENAI.models[0]

_TEXT_ONLY = ModelDefinition(
    provider_id="x",
    model_id="text-only",
    display_name="Text Only",
    capabilities=ModelCapabilities(structured_output=True),
)

_NO_STRUCTURE = ModelDefinition(
    provider_id="x",
    model_id="no-structure",
    display_name="No Structure",
    capabilities=ModelCapabilities(image_input=True),
)


class _RetiredProvider:
    provider_id = "fake"

    def resolve_models(self):
        return [
            ModelDefinition("fake", "old-model", "Old", status="retired"),
            ModelDefinition("fake", "current-model", "Current"),
        ]


def test_digest_needs_text_in_out_and_structure():
    assert supports_digest(_GPT4O) is True
    assert supports_digest(_TEXT_ONLY) is True
    assert supports_digest(_NO_STRUCTURE) is False


def test_vision_needs_image_input():
    assert supports_vision(_GPT4O) is True
    assert supports_vision(_TEXT_ONLY) is False


def test_text_only_model_passes_digest_route_and_fails_vision_route():
    assert check_model_for_routes(_TEXT_ONLY, {"digest"}) == []
    problems = check_model_for_routes(_TEXT_ONLY, {"vision"})
    assert len(problems) == 1 and "vision" in problems[0]
    both = check_model_for_routes(_TEXT_ONLY, {"digest", "vision"})
    assert len(both) == 1  # only the vision leg fails


def test_hybrid_capable_model_has_no_problems():
    assert check_model_for_routes(_GPT4O, {"digest", "vision"}) == []
    assert check_model_for_routes(_GPT4O, []) == []


def test_resolve_model_known_active_and_unknown():
    provider = MockProvider()
    known = resolve_model(provider, "mock-model")
    assert known.definition is not None
    assert known.warning is None

    unknown = resolve_model(provider, "mystery")
    assert unknown.definition is None
    assert "mystery" in (unknown.warning or "")
    assert "mock" in (unknown.warning or "")


def test_resolve_model_flags_retired_entries():
    retired = resolve_model(_RetiredProvider(), "old-model")
    assert retired.definition is not None
    assert retired.definition.status == "retired"
    assert "retired" in (retired.warning or "")

    current = resolve_model(_RetiredProvider(), "current-model")
    assert current.warning is None
