"""Phase 3: the mock provider is deterministic and programmable."""

import json

import pytest

from pdf2epub.providers.base import ProviderAdapter
from pdf2epub.providers.errors import ProviderError, ProviderResponseError
from pdf2epub.providers.mock import MockProvider


def digest_payload_for(page_nums):
    return json.dumps(
        {
            "instruction": "Convert each page layout digest into semantic XHTML.",
            "page_count": len(page_nums),
            "pages": [
                {"page_num": n, "layout_digest": []} for n in page_nums
            ],
        }
    )


def test_mock_conforms_to_the_contract():
    provider = MockProvider()
    assert isinstance(provider, ProviderAdapter)
    assert provider.provider_id == "mock"


def test_mock_credential_check_is_deterministic():
    provider = MockProvider()
    assert provider.validate_credentials("test-key") is True
    assert provider.validate_credentials("anything-else") is False


def test_mock_lists_its_models():
    assert [m.model_id for m in MockProvider().resolve_models()] == ["mock-model"]


def test_unknown_model_is_rejected():
    with pytest.raises(ProviderError):
        MockProvider().create_llm_callable("nope", "test-key")


def test_default_response_matches_requested_page_count():
    provider = MockProvider()
    client = provider.create_llm_callable("mock-model", "test-key")
    raw = client("SYS", digest_payload_for([7, 8, 9]))
    pages = json.loads(raw)["xhtml_pages"]
    assert len(pages) == 3
    assert "<p>Mock page 7</p>" in pages[0]


def test_vision_style_payload_gets_one_page_and_records_image():
    provider = MockProvider()
    client = provider.create_llm_callable("mock-model", "test-key")
    raw = client("SYS", "Transcribe page 4 into XHTML.", image_b64="aGk=")
    assert len(json.loads(raw)["xhtml_pages"]) == 1
    assert provider.calls[-1]["image_b64"] == "aGk="
    assert provider.calls[-1]["system_prompt"] == "SYS"


def test_scripted_responses_are_returned_verbatim_then_queue_empties():
    provider = MockProvider(responses=["not json at all"])
    client = provider.create_llm_callable("mock-model", "test-key")
    assert client("SYS", digest_payload_for([1])) == "not json at all"
    # queue exhausted -> default behaviour returns
    assert json.loads(client("SYS", digest_payload_for([2])))["xhtml_pages"]


def test_raise_mode_propagates_the_configured_error():
    boom = ProviderResponseError("garbled response")
    provider = MockProvider(raise_error=boom)
    client = provider.create_llm_callable("mock-model", "test-key")
    with pytest.raises(ProviderResponseError):
        client("SYS", digest_payload_for([1]))
