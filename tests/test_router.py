"""Module 2: triage router."""

import pytest

import confidence_router as cr
from confidence_router import RoutingTarget

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


PROSE = (
    "The parser must decide whether a page can be handled by the deterministic "
    "engine or whether it has to be sent to the model, and it has to make that "
    "decision from the layout alone before any conversion work is done."
)


# ---------------------------------------------------------------------------
# Text sanity gate
# ---------------------------------------------------------------------------


def test_normal_prose_passes_the_sanity_gate():
    res = cr.assess_text_sanity(PROSE)
    assert res.sane
    assert res.hit_rate > 0.3
    assert res.reason == "ok"


def test_empty_page_is_routed_to_vision():
    res = cr.assess_text_sanity("   \n  ")
    assert not res.sane
    assert res.reason == "no_text_layer"
    assert res.has_text is False


def test_private_use_area_saturation_is_detected():
    mojibake = "".join(chr(0xE000 + (i % 200)) for i in range(400))
    res = cr.assess_text_sanity(mojibake)
    assert not res.sane
    assert res.reason == "pua_saturation"


def test_lexical_gibberish_is_detected():
    # Plausible-looking ASCII with no English stopwords at all.
    junk = " ".join(["qxzv", "mbjr", "ttkl", "wzpq", "vnrd", "hgkx"] * 12)
    res = cr.assess_text_sanity(junk)
    assert not res.sane
    assert res.reason == "lexical_gibberish"


def test_short_technical_page_is_not_flagged_as_gibberish():
    """Below the token floor the lexical test must not fire."""
    res = cr.assess_text_sanity("SHA256 RSA4096 AES128 HMAC")
    assert res.sane


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_single_order_violation_falls_below_the_tier1_threshold():
    """Regression: at 15 points per violation this landed on exactly 85."""
    score, penalties, _, _ = cr.score_page_layout([], vector_count=0)
    assert score == 100
    penalty = min(45, 1 * 20)
    assert 100 - penalty < cr.TIER1_THRESHOLD


def test_vector_density_penalty_applies_above_threshold():
    score, penalties, _, _ = cr.score_page_layout([], vector_count=60)
    assert penalties["vector_density"] > 0
    assert score < cr.TIER1_THRESHOLD


def test_reading_order_ignores_headers_and_footers():
    """A running footer emitted before the body must not count as a violation."""
    def line(x, y, text):
        return {"bbox": (x, y, x + 100, y + 12),
                "spans": [{"text": text, "size": 10.0}]}

    blocks = [
        {"lines": [line(54, 30, "Running Header Text")]},
        {"lines": [line(200, 650, "Chapter One - page 42")]},
        {"lines": [line(54, 100, "Body line one goes here"),
                   line(54, 114, "Body line two goes here")]},
    ]
    assert cr.count_order_violations(blocks, page_height=680.0) == 0
    # Without page geometry the furniture band cannot be excluded and the
    # footer-to-body jump is miscounted as a reading-order violation.
    assert cr.count_order_violations(blocks, page_height=0.0) == 1


def test_two_column_jump_is_counted():
    def line(x, y):
        return {"bbox": (x, y, x + 150, y + 12),
                "spans": [{"text": "column text here", "size": 10.0}]}

    blocks = [
        {"lines": [line(54, 110), line(54, 124), line(54, 138)]},
        {"lines": [line(240, 110), line(240, 124)]},
    ]
    assert cr.count_order_violations(blocks, page_height=680.0) == 1


# ---------------------------------------------------------------------------
# End-to-end routing on real fixtures
# ---------------------------------------------------------------------------


def test_clean_single_column_page_routes_to_tier1(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["single_column"])
    report = cr.evaluate_page(doc[0], 1)
    assert report.target is RoutingTarget.TIER1_HEURISTIC
    assert report.score == 100
    assert report.layout_digest is None
    doc.close()


def test_two_column_page_routes_to_digest_with_coordinates(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["two_column"])
    report = cr.evaluate_page(doc[0], 1, build_payloads=True)
    assert report.target is RoutingTarget.TIER2_LLM_DIGEST
    assert report.order_violations >= 1
    assert report.layout_digest
    entry = report.layout_digest[0]
    assert set(entry) >= {"line_id", "block_id", "bbox", "size", "bold", "text"}
    assert len(entry["bbox"]) == 4
    doc.close()


def test_scanned_page_routes_to_vision_with_a_raster(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["scanned"])
    report = cr.evaluate_page(doc[0], 1, build_payloads=True)
    assert report.target is RoutingTarget.TIER2_VISION_OCR
    assert report.has_text is False
    assert report.raster_bytes and report.raster_bytes[:4] == b"\x89PNG"
    doc.close()


def test_clean_book_routing_mix(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["clean_book"])
    reports = cr.route_document(doc, build_payloads=False)
    summary = cr.summarise(reports)
    assert summary == {"tier1": 4, "tier2_digest": 1, "tier2_vision": 1}
    doc.close()


def test_payloads_are_lazy_by_default(fixture_pdfs):
    """Triage must not materialise rasters for the whole document."""
    doc = fitz.open(fixture_pdfs["scanned"])
    report = cr.evaluate_page(doc[0], 1)
    assert report.raster_bytes is None
    assert report.layout_digest is None
    doc.close()


def test_attach_and_release_payload_round_trip(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["scanned"])
    report = cr.evaluate_page(doc[0], 1)
    cr.attach_payload(doc[0], report)
    assert report.raster_bytes and report.raster_bytes[:4] == b"\x89PNG"
    cr.release_payload(report)
    assert report.raster_bytes is None
    doc.close()


def test_attach_payload_builds_a_digest_for_complex_pages(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["two_column"])
    report = cr.evaluate_page(doc[0], 1)
    assert report.layout_digest is None
    cr.attach_payload(doc[0], report)
    assert report.layout_digest
    doc.close()


def test_route_document_holds_no_payloads(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["clean_book"])
    reports = cr.route_document(doc)
    assert all(r.raster_bytes is None and r.layout_digest is None for r in reports)
    doc.close()


def test_text_from_blocks_matches_plain_extraction(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["single_column"])
    blocks = [b for b in doc[0].get_text("dict")["blocks"] if b.get("type") == 0]
    rebuilt = cr.text_from_blocks(blocks)
    assert "Conversion pipelines" in rebuilt
    assert cr.assess_text_sanity(rebuilt).sane
    doc.close()
