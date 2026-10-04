"""Phase 3: the contract drives the real engine.

Shape compatibility is proven here, not asserted in prose: a callable built
through the provider contract must be able to replace ``llm_client_fn`` in
the actual Tier2Handler, survive the batch-integrity ladder, and degrade
cleanly to the deterministic fallback when a normalized error crosses the
boundary.
"""

import json

from pdf2epub.engine.tier2_llm_handler import Tier2Handler, Tier2Request
from pdf2epub.providers.errors import ProviderResponseError
from pdf2epub.providers.mock import MockProvider


def _digest_line(page_num):
    return [
        {
            "line_id": 1,
            "block_id": 1,
            "bbox": [54.0, 90.0, 260.0, 102.0],
            "size": 10.0,
            "bold": False,
            "italic": False,
            "text": f"line on page {page_num}",
        }
    ]


def _requests(*page_nums):
    return [
        Tier2Request(page_num=n, layout_digest=_digest_line(n)) for n in page_nums
    ]


def test_mock_callable_drives_the_real_tier2_handler(tmp_path):
    provider = MockProvider()
    client = provider.create_llm_callable("mock-model", "test-key")
    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)

    pages = handler.process_batch(_requests(1, 2))
    assert len(pages) == 2
    assert "Mock page 1" in pages[0]
    assert "Mock page 2" in pages[1]
    assert handler.stats["api_calls"] == 1

    # second identical batch is served from cache, not the mock
    again = handler.process_batch(_requests(1, 2))
    assert again == pages
    assert handler.stats["cache_hits"] == 1
    assert handler.stats["api_calls"] == 1


def test_short_scripted_batch_recovers_via_single_page_calls(tmp_path):
    provider = MockProvider(
        responses=[json.dumps({"xhtml_pages": ["<p>only one</p>"]})]
    )
    client = provider.create_llm_callable("mock-model", "test-key")
    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)

    pages = handler.process_batch(_requests(1, 2))
    # the one-page answer triggers the per-page re-prompt ladder, whose
    # default mock responses are well formed
    assert len(pages) == 2
    assert "Mock page 1" in pages[0]
    assert "Mock page 2" in pages[1]


def test_normalized_error_degrades_to_deterministic_fallback(tmp_path):
    provider = MockProvider(raise_error=ProviderResponseError("garbled"))
    client = provider.create_llm_callable("mock-model", "test-key")
    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path, max_retries=0)

    pages = handler.process_batch(_requests(3))

    # the engine shields the boundary error and serves the page from the
    # deterministic digest fallback -- with real page text, not emptiness
    assert len(pages) == 1
    assert "line on page 3" in pages[0]
    # v3 cache discipline: failed calls must leave nothing behind
    assert list(tmp_path.glob("*.json")) == []
