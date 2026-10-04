"""Phase 3: model descriptors are frozen data with honest defaults."""

import pytest

from pdf2epub.providers.models import ModelCapabilities, ModelDefinition


def test_model_definition_is_frozen():
    model = ModelDefinition(provider_id="x", model_id="y", display_name="Y")
    with pytest.raises(AttributeError):
        model.model_id = "z"


def test_capabilities_default_shape():
    caps = ModelCapabilities()
    assert caps.text_input is True
    assert caps.text_output is True
    assert caps.image_input is False
    assert caps.structured_output is False
    assert caps.max_context is None


def test_capabilities_and_lifecycle_are_preserved():
    caps = ModelCapabilities(
        image_input=True, structured_output=True, max_context=128000
    )
    model = ModelDefinition(
        "p", "m", "M", capabilities=caps, status="experimental"
    )
    assert model.capabilities is caps
    assert model.status == "experimental"
    assert model.capabilities.max_context == 128000
