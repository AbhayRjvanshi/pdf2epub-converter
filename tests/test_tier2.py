"""Module 3: AI semantic engine - caching, batching, XHTML repair."""

import json

import pytest

import tier2_llm_handler as t2
from tier2_llm_handler import Tier2Handler, Tier2Request


def digest(page_num=1, texts=("Heading", "Body text here")):
    return Tier2Request(
        page_num=page_num,
        layout_digest=[
            {
                "line_id": i + 1,
                "block_id": 0,
                "bbox": [54.0, 100.0 + i * 14, 300.0, 112.0 + i * 14],
                "size": 14.0 if i == 0 else 10.0,
                "bold": i == 0,
                "italic": False,
                "text": t,
            }
            for i, t in enumerate(texts)
        ],
    )


def fake_client(pages):
    """Client returning a fixed number of pages, counting its calls."""
    calls = []

    def client(system_prompt, payload, image_b64=None):
        calls.append((system_prompt, payload, image_b64))
        return json.dumps({"xhtml_pages": list(pages)})

    client.calls = calls  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Cache key composition
# ---------------------------------------------------------------------------


def test_cache_key_changes_with_prompt_model_and_temperature():
    base = t2.get_cache_key("payload", "prompt", "model-a", 0.0)
    assert base != t2.get_cache_key("payload", "prompt EDITED", "model-a", 0.0)
    assert base != t2.get_cache_key("payload", "prompt", "model-b", 0.0)
    assert base != t2.get_cache_key("payload", "prompt", "model-a", 0.7)
    assert base != t2.get_cache_key("payload", "prompt", "model-a", 0.0, "schema/v9")
    assert base == t2.get_cache_key("payload", "prompt", "model-a", 0.0)


def test_vision_cache_key_is_derived_from_image_not_page_number():
    """Regression: keying on 'VISION_PAGE_{n}' collides across documents."""
    a = Tier2Request(page_num=1, raster_bytes=b"\x89PNG-image-A")
    b = Tier2Request(page_num=1, raster_bytes=b"\x89PNG-image-B")
    assert a.payload_fingerprint() != b.payload_fingerprint()

    same = Tier2Request(page_num=99, raster_bytes=b"\x89PNG-image-A")
    assert a.payload_fingerprint() == same.payload_fingerprint()


def test_cache_prevents_a_second_api_call(tmp_path):
    client = fake_client(["<p>one</p>"])
    h1 = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    h1.process_batch([digest()])
    assert len(client.calls) == 1

    h2 = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    out = h2.process_batch([digest()])
    assert len(client.calls) == 1
    assert h2.stats["cache_hits"] == 1
    assert out == ["<p>one</p>"]


def test_offline_fallbacks_are_not_cached_and_online_model_runs_later(tmp_path):
    req = digest()
    offline = Tier2Handler(cache_dir=tmp_path)
    offline.process_batch([req])
    assert list(tmp_path.glob("*.json")) == []

    client = fake_client(["<p>online result</p>"])
    online = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    assert online.process_batch([req]) == ["<p>online result</p>"]
    assert len(client.calls) == 1


def test_failed_model_fallback_is_not_cached(tmp_path):
    req = digest()
    broken = Tier2Handler(
        llm_client_fn=lambda *_: (_ for _ in ()).throw(ConnectionError("offline")),
        cache_dir=tmp_path,
        max_retries=0,
    )
    broken.process_batch([req])
    assert list(tmp_path.glob("*.json")) == []

    client = fake_client(["<p>recovered online</p>"])
    recovered = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    assert recovered.process_batch([req]) == ["<p>recovered online</p>"]
    assert len(client.calls) == 1


def test_vision_fallbacks_are_not_cached(tmp_path):
    req = Tier2Request(page_num=1, raster_bytes=b"\x89PNG-image")
    offline = Tier2Handler(cache_dir=tmp_path)
    offline.process_batch([req])
    assert list(tmp_path.glob("*.json")) == []

    broken = Tier2Handler(
        llm_client_fn=lambda *_: (_ for _ in ()).throw(ConnectionError("offline")),
        cache_dir=tmp_path,
        max_retries=0,
    )
    broken.process_batch([req])
    assert list(tmp_path.glob("*.json")) == []

    client = fake_client(["<p>online OCR</p>"])
    online = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    assert online.process_batch([req]) == ["<p>online OCR</p>"]
    assert len(client.calls) == 1


def test_malformed_cache_entry_is_deleted_and_treated_as_miss(tmp_path):
    handler = Tier2Handler(cache_dir=tmp_path)
    path = handler._cache_path("bad-entry")
    path.write_text('{"xhtml_pages": [42]}', encoding="utf-8")
    assert handler._cache_read("bad-entry") is None
    assert not path.exists()


# ---------------------------------------------------------------------------
# Batch integrity
# ---------------------------------------------------------------------------


def test_short_batch_response_does_not_crash_and_is_repaired(tmp_path):
    """Regression: a ragged array used to raise, or silently drop a page."""
    client = fake_client(["<p>only one page</p>"])  # two requested
    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    out = handler.process_batch([digest(1), digest(2, ("Other", "Page"))])
    assert len(out) == 2
    assert all(isinstance(p, str) and p for p in out)
    assert handler.stats["repairs"] == 1


def test_output_count_always_matches_input_count(tmp_path):
    handler = Tier2Handler(cache_dir=tmp_path)  # offline mock
    reqs = [digest(i) for i in range(1, 6)]
    assert len(handler.process_batch(reqs)) == 5


def test_mixed_vision_and_digest_batch_keeps_order(tmp_path):
    handler = Tier2Handler(cache_dir=tmp_path)
    reqs = [
        digest(1),
        Tier2Request(page_num=2, raster_bytes=b"\x89PNGfake"),
        digest(3, ("Third", "Page here")),
    ]
    out = handler.process_batch(reqs)
    assert len(out) == 3
    assert "page 2" in out[1]


def test_model_failure_falls_back_instead_of_aborting(tmp_path):
    def broken(system_prompt, payload, image_b64=None):
        raise ConnectionError("network down")

    handler = Tier2Handler(llm_client_fn=broken, cache_dir=tmp_path, max_retries=0)
    out = handler.process_batch([digest()])
    assert len(out) == 1
    assert "Heading" in out[0]
    assert handler.stats["fallbacks"] >= 1


def test_empty_request_list(tmp_path):
    assert Tier2Handler(cache_dir=tmp_path).process_batch([]) == []


# ---------------------------------------------------------------------------
# Deterministic fallback quality
# ---------------------------------------------------------------------------


def test_digest_fallback_reads_columns_in_order():
    req = Tier2Request(
        page_num=1,
        layout_digest=[
            {"bbox": [54, 100, 200, 112], "size": 10.0, "text": "left one"},
            {"bbox": [300, 100, 400, 112], "size": 10.0, "text": "right one"},
            {"bbox": [54, 114, 200, 126], "size": 10.0, "text": "left two"},
            {"bbox": [300, 114, 400, 126], "size": 10.0, "text": "right two"},
        ],
    )
    out = t2._digest_fallback(req)
    order = [out.index(t) for t in ("left one", "left two", "right one", "right two")]
    assert order == sorted(order)


def test_digest_fallback_promotes_large_text_to_headings():
    req = Tier2Request(
        page_num=1,
        layout_digest=[
            {"bbox": [54, 90, 200, 110], "size": 18.0, "text": "Big Title"},
            {"bbox": [54, 120, 200, 132], "size": 10.0, "text": "body one"},
            {"bbox": [54, 134, 200, 146], "size": 10.0, "text": "body two"},
        ],
    )
    out = t2._digest_fallback(req)
    assert "<h1>Big Title</h1>" in out


# ---------------------------------------------------------------------------
# XHTML sanitise / repair gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,must_contain,must_not_contain",
    [
        ("```xml\n<p>fenced</p>\n```", "<p>fenced</p>", "```"),
        ("<p>AT&T merged</p>", "AT&amp;T", "AT&T "),
        ("<p>line<br>break</p>", "<br/>", "<br>b"),
        ("<p>ok</p><script>alert(1)</script>", "<p>ok</p>", "script"),
        ("<p>already &amp; fine</p>", "&amp;", "&amp;amp;"),
    ],
)
def test_sanitizer_cases(raw, must_contain, must_not_contain):
    out = t2.sanitize_and_validate_xhtml(raw)
    assert must_contain in out
    assert must_not_contain not in out
    assert t2.is_well_formed(out)[0]


def test_sanitizer_repairs_unclosed_tags():
    out = t2.sanitize_and_validate_xhtml("<p>open <strong>bold</p>")
    assert t2.is_well_formed(out)[0]
    assert "bold" in out


def test_sanitizer_last_resort_keeps_the_words():
    out = t2.sanitize_and_validate_xhtml("<p>alpha <<>> beta</p>")
    assert t2.is_well_formed(out)[0]
    assert "alpha" in out and "beta" in out


def test_sanitizer_handles_empty_input():
    assert t2.sanitize_and_validate_xhtml("") == ""
    assert t2.sanitize_and_validate_xhtml("   ") == ""


def test_sanitised_output_of_the_model_is_well_formed(tmp_path):
    client = fake_client(["```json\n<p>Q&A <b>bold</b><br></p>\n```"])
    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    out = handler.process_batch([digest()])[0]
    assert t2.is_well_formed(out)[0]
    assert "&amp;" in out


def test_json_fences_are_stripped_before_parsing(tmp_path):
    def client(system_prompt, payload, image_b64=None):
        return '```json\n{"xhtml_pages": ["<p>ok</p>"]}\n```'

    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    assert handler.process_batch([digest()]) == ["<p>ok</p>"]
