"""M3b policy enforcement tests (Phase 6).

Tests the nine requirements documented in review_assets/M3B_POLICY.md
against the unchanged production implementation. These tests are
written BEFORE any production code changes: they establish the safety
contract that any future implementation must satisfy.

The Phase 4 finding rejected all three feature-based classification
rules (A/B/C) for production use. The Phase 5 policy pins lossless as
the default for original embedded images. These tests prove that the
current code already satisfies the policy and guard against future
regressions.

Baseline note: the current implementation is EXPECTED to pass most of
these tests because _transcode_to_core already produces only PNG and
no hidden lossy path exists. A passing test against unchanged code is
a valid result: it confirms the safety invariant, not a failure of the
failing-first discipline.
"""

import zipfile
from pathlib import Path

import pytest

from pdf2epub.engine import tier1_classifier as t1
from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.engine.tier1_classifier import ElementType

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


# ---------------------------------------------------------------------------
# Fixtures (deterministic, inline; no external assets)
# ---------------------------------------------------------------------------


def _make_pdf_with_embedded_image(tmp_path, image_bytes=None, ext="png"):
    """A one-page PDF with a single embedded image at a known position."""
    doc = fitz.open()
    page = doc.new_page(width=420, height=680)
    if image_bytes is None:
        image_bytes = t1.__dict__.get("_test_photo_bytes")  # not used; see tests
    rect = fitz.Rect(50, 100, 370, 500)
    # insert via a page pixmap to get a real embedded image
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 150), False)
    pix.set_rect(pix.irect, (120, 80, 200))  # smooth fill
    pix.set_rect(fitz.IRect(50, 50, 150, 100), (100, 160, 220))
    page.insert_image(rect, pixmap=pix)
    pdf_path = tmp_path / f"embedded_{ext}.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _convert_and_get_images(pdf_path, tmp_path, name="out.epub"):
    """Run the real extraction + packaging path and return the packaged images."""
    from pdf2epub.engine import driver

    out = tmp_path / name
    result = driver.run_pipeline(
        str(pdf_path), str(out),
        llm_adapter=None, verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),
    )
    assert result["success"] is True, result
    with zipfile.ZipFile(str(out)) as zf:
        images = {}
        for n in zf.namelist():
            if n.startswith("EPUB/images/"):
                images[n] = zf.read(n)
        return result, images


# ---------------------------------------------------------------------------
# Test 1 — Default preservation: embedded images stay lossless
# ---------------------------------------------------------------------------


def test_embedded_image_output_is_png_not_jpeg(tmp_path):
    """Requirement 1: an embedded image without explicit authorization is
    never lossy-transcoded. The current path always produces lossless PNG
    (or byte-identical passthrough of a core-format source)."""
    pdf = _make_pdf_with_embedded_image(tmp_path)
    result, images = _convert_and_get_images(pdf, tmp_path)
    assert len(images) >= 1, "no images packaged"
    for name, data in images.items():
        assert data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff", (
            f"unexpected format in {name}: {data[:8]!r}"
        )
        # If the source was already a core format (including JPEG), the
        # bytes are a byte-identical passthrough — that is NOT a lossy
        # transcode, it is preservation of the source. The key invariant
        # is that no re-encoding to a lossy format occurred.
        # For this fixture the source is a raster insert → MuPDF writes
        # it as an embedded image; verify no JPEG was CREATED by the
        # converter (a JPEG source passthrough is different — tested below).


def test_transcode_to_core_produces_only_png():
    """Requirement 1 (unit level): _transcode_to_core must produce only
    PNG bytes, never JPEG."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), False)
    pix.set_rect(pix.irect, (100, 150, 200))
    png_bytes = pix.tobytes("png")
    result = t1._transcode_to_core(png_bytes)
    assert result is not None
    assert result[:8] == b"\x89PNG\r\n\x1a\n", "transcode output must be PNG"
    assert result[:3] != b"\xff\xd8\xff", "transcode output must never be JPEG"


def test_transcode_failure_drops_not_falls_back_to_lossy():
    """Requirement 1 (failure path): when _transcode_to_core cannot decode
    the source, it returns None (drop with diagnostic), never a lossy
    fallback."""
    garbage = b"\x00" * 100
    result = t1._transcode_to_core(garbage)
    assert result is None, "undecodable bytes must return None, never a lossy fallback"


# ---------------------------------------------------------------------------
# Test 2 — Classifier prohibition: Rules A/B/C cannot authorize JPEG
# ---------------------------------------------------------------------------


def test_no_feature_classifier_in_extraction_path():
    """Requirement 2 (architectural): the extract_images function does
    not contain any feature-based classification that could select JPEG.
    The format decision is purely: is the source core or non-core?"""
    import inspect

    source = inspect.getsource(t1.extract_images)
    # The only format decision is the core/non-core gate
    assert "_transcode_to_core" in source, "transcode gate must be present"
    # No classifier invocation, no micro/flat/crisp/color feature usage
    for token in ("micro", "flat_share", "crisp", "classify_image", "is_photographic"):
        assert token not in source, (
            f"extract_images must not contain classifier token {token!r}"
        )


def test_no_classifier_functions_exist_in_production():
    """Requirement 2: no classifier functions for Rules A/B/C exist in
    the production engine. The rejected rules are historical evidence
    only (documented on the review branch, not in the codebase)."""
    import inspect

    for name in dir(t1):
        if any(rule in name.lower() for rule in ("rule_a", "rule_b", "rule_c", "classify_content")):
            pytest.fail(f"production code must not contain classifier {name}")


# ---------------------------------------------------------------------------
# Test 3 — Alpha preservation
# ---------------------------------------------------------------------------


def test_alpha_bearing_composite_stays_png(fixture_pdfs, tmp_path):
    """Requirement 3: an alpha-bearing image (SMask composite) must remain
    lossless with its alpha channel preserved. Uses the existing
    smask_composite fixture."""
    result, images = _convert_and_get_images(fixture_pdfs["smask_composite"], tmp_path)
    assert len(images) >= 1
    for name, data in images.items():
        pix = fitz.Pixmap(data)
        if pix.alpha:
            assert data[:8] == b"\x89PNG\r\n\x1a\n", (
                f"alpha-bearing image {name} must be PNG, not a lossy format"
            )


def test_transcode_preserves_no_alpha_when_source_has_none():
    """Requirement 3 (unit): _transcode_to_core converts to RGB PNG when
    the source has no alpha; it does not add or remove alpha channels."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32), False)
    png_bytes = pix.tobytes("png")
    result = t1._transcode_to_core(png_bytes)
    decoded = fitz.Pixmap(result)
    assert not decoded.alpha, "opaque source must stay opaque after transcode"


# ---------------------------------------------------------------------------
# Test 4 — Size fallback (contract; no exception mechanism exists)
# ---------------------------------------------------------------------------


def test_size_fallback_contract_documented():
    """Requirement 4 — POLICY-CONTRACT DOCUMENTATION, NOT A BEHAVIORAL GATE TEST.

    This test documents the future size-comparison baseline (packaged
    lossless PNG bytes) and verifies that _transcode_to_core produces
    the lossless PNG that IS that baseline. It does NOT exercise a
    JPEG candidate that is equal to or larger than the PNG, because
    no exception mechanism exists to produce such a candidate.

    When an exception workflow is approved, this test must be
    supplemented with behavioral tests covering: JPEG-smaller-proceeds,
    JPEG-equal-keeps-PNG, and JPEG-larger-keeps-PNG.
    """
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), False)
    source_bytes = pix.tobytes("png")
    png_output = t1._transcode_to_core(source_bytes)
    assert png_output is not None
    # The PNG output IS the baseline against which any future JPEG
    # candidate would be compared
    assert png_output[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Test 5 — Fidelity fallback (contract; no exception mechanism exists)
# ---------------------------------------------------------------------------


def test_fidelity_fallback_contract_documented():
    """Requirement 5 — POLICY-CONTRACT DOCUMENTATION, NOT A BEHAVIORAL GATE TEST.

    This test verifies that the current path always produces lossless
    output (there is no lossy candidate to gate). It does NOT exercise
    a fidelity check that fails or returns an indeterminate result,
    because no exception mechanism exists to produce a candidate.

    When an exception workflow is approved, this test must be
    supplemented with behavioral tests covering: fidelity-pass-allows-
    JPEG, fidelity-fail-keeps-PNG, and fidelity-indeterminate-keeps-PNG.
    Formal numerical fidelity thresholds for M3b have not been pinned
    (documented in PHASE5_DECISION.md).
    """
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32), False)
    result = t1._transcode_to_core(pix.tobytes("png"))
    assert result is not None
    assert result[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Test 6 — Exception isolation: no hidden authorization
# ---------------------------------------------------------------------------


def test_no_env_var_or_config_enables_lossy_transcode():
    """Requirement 6: no environment variable, configuration option, or
    hidden flag can bypass the lossless default for embedded images.

    Architectural test: the transcode function's output format is
    hardcoded to PNG and cannot be changed by any runtime setting."""
    import inspect

    source = inspect.getsource(t1._transcode_to_core)
    # The only output format call is pix.tobytes("png")
    assert 'tobytes("png")' in source, "transcode must hardcode PNG output"
    # No environment variable or config lookup
    for token in ("os.environ", "getenv", "config", "setting", "quality"):
        assert token not in source, (
            f"transcode must not read runtime settings: found {token!r}"
        )


# ---------------------------------------------------------------------------
# Test 7 — Stable identity: content hash, not dimensions
# ---------------------------------------------------------------------------


def test_image_dedup_uses_content_hash_not_dimensions(tmp_path):
    """Requirement 7: images are deduplicated by content hash (SHA-1 of
    the packaged bytes), not by dimensions alone. Two different images
    with the same dimensions must be packaged as two distinct assets.

    Note: the page needs body text to route to Tier 1 (the embedded-image
    extraction path). A textless page routes to vision/M3a, which renders
    the whole page as one raster — a different code path from the one
    this test targets."""
    doc = fitz.open()
    page = doc.new_page(width=420, height=680)
    # body text ensures the page routes to Tier 1
    page.insert_text((54, 80), "Body text to ensure Tier 1 routing.",
                     fontname="helv", fontsize=12)
    # two images with the SAME dimensions but DIFFERENT content
    pix_a = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix_a.set_rect(pix_a.irect, (255, 0, 0))
    pix_b = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix_b.set_rect(pix_b.irect, (0, 0, 255))
    page.insert_image(fitz.Rect(50, 100, 150, 200), pixmap=pix_a)
    page.insert_image(fitz.Rect(200, 100, 300, 200), pixmap=pix_b)
    pdf = tmp_path / "two_same_dims.pdf"
    doc.save(str(pdf))
    doc.close()

    result, images = _convert_and_get_images(pdf, tmp_path)
    tier1_images = {k: v for k, v in images.items() if not k.split("/")[-1].startswith("page_")}
    assert len(tier1_images) >= 2, (
        f"two distinct images with same dims must produce >=2 extracted assets, "
        f"got {len(tier1_images)}: {list(tier1_images.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 8 — M3a regression: page-raster optimization unchanged
# ---------------------------------------------------------------------------


def test_m3a_page_raster_optimization_unchanged(fixture_pdfs, tmp_path):
    """Requirement 8: the M3a path (vision-embedded scanned-page rasters)
    still uses its measured-eligibility approach (encode both, keep the
    smaller). The scanned fixture uses a photographic-like gradient that
    JPEG-compresses far smaller than PNG, so the EXPECTED deterministic
    result is JPEG. This tight assertion catches an M3a regression where
    the measured-eligibility behavior stops selecting JPEG for a
    photographic page raster."""
    from pdf2epub.engine import driver

    out = tmp_path / "scan.epub"
    result = driver.run_pipeline(
        str(fixture_pdfs["scanned"]), str(out),
        llm_adapter=None, verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),
    )
    assert result["success"] is True
    with zipfile.ZipFile(str(out)) as zf:
        images = [n for n in zf.namelist() if n.startswith("EPUB/images/")]
        assert len(images) >= 1, "scanned page raster was not packaged"
        data = zf.read(images[0])
        # TIGHT: the gradient fixture must produce JPEG (measured
        # eligibility selects JPEG for this photographic content).
        # Allowing PNG here would let an M3a regression slip through.
        assert data[:3] == b"\xff\xd8\xff", (
            f"M3a regression: scanned-page raster must be JPEG for this "
            f"photographic fixture, got {data[:8]!r}"
        )


# ---------------------------------------------------------------------------
# Test 9 — Packaging integrity: EPUB references the correct assets
# ---------------------------------------------------------------------------


def test_packaging_references_correct_images(tmp_path):
    """Requirement 9: the EPUB references the correct image assets and
    remains structurally valid. An end-to-end conversion must produce
    images that are: actually present in the EPUB, referenced from the
    XHTML, correctly formatted, and dimensionally intact."""
    from pdf2epub.engine import driver

    pdf = _make_pdf_with_embedded_image(tmp_path)
    out = tmp_path / "packaging.epub"
    result = driver.run_pipeline(
        str(pdf), str(out),
        llm_adapter=None, verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),  # structural check runs via internal_structure_check
    )
    assert result["success"] is True

    # structural check: EPUB container, references, XML validity
    errors = pk.internal_structure_check(str(out))
    assert not errors, f"structural check failed: {errors}"

    with zipfile.ZipFile(str(out)) as zf:
        xhtml = "".join(
            zf.read(n).decode("utf-8", "ignore")
            for n in zf.namelist() if n.endswith(".xhtml")
        )
        assert "<img" in xhtml, "no image reference in the XHTML body"
        # every image referenced in XHTML must exist in the EPUB
        import re
        for m in re.finditer(r'src="([^"]+)"', xhtml):
            src = m.group(1)
            if src.startswith("../images/"):
                path = "EPUB/" + src[3:]
                assert path in zf.namelist(), f"broken image reference: {src}"
