"""Env-gated integration test against the real Flower Garden PDF.

Round 1 reproduction test: the confirmed defects (ten false h4s, mask
artifact figures, lost transparency, per-line paragraph shattering,
<strong>-wrapped narrative) are asserted ABSENT against the actual
document that exposed them, not only against synthetic fixtures.

Enable by exporting ``PDF2EPUB_FLOWER_PDF=<path to the .pdf>``. The
offline suite stays deterministic: without the variable every test in
this module skips with an explicit reason.

EPUBCheck runs when installed and reports honestly otherwise: it is a
separate test that skips with "not installed", never silently passing.
"""

import os
import re
import zipfile
from pathlib import Path

import pytest

PDF_ENV = "PDF2EPUB_FLOWER_PDF"
_pdf_path = os.environ.get(PDF_ENV, "")
pytestmark = pytest.mark.skipif(
    not _pdf_path or not Path(_pdf_path).is_file(),
    reason=f"{PDF_ENV} not set or file missing; real-book test skipped",
)

# Distinctive fragments of the ten confirmed false h4s (flower-garden
# page 24). None of these may appear in any heading or nav entry.
FALSE_HEADING_FRAGMENTS = (
    "wait to tell their mom",
    "ran to the house and through",
    "come-on, come-on",
    "grabbed her dad",
    "done a great job",
    "mom said",
    "gardens.",
    "hurry!",
    "shouted.",
    "outside and see our gardens",
)


def _convert(tmp_path):
    from pdf2epub.engine import driver

    out = tmp_path / "flower_garden.epub"
    # Service-equivalent invocation: the application layer substitutes
    # sentinels for missing metadata before the engine boundary.
    result = driver.run_pipeline(
        _pdf_path,
        str(out),
        llm_adapter=None,
        verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),  # internal structural check only: deterministic
    )
    return result, out


def _epub_text(zf, suffix=".xhtml"):
    parts = []
    for name in zf.namelist():
        if name.endswith(suffix):
            parts.append(zf.read(name).decode("utf-8"))
    return "\n".join(parts)


def test_flower_garden_round_1_gates(tmp_path):
    result, out = _convert(tmp_path)
    assert result["success"] is True, result
    zf = zipfile.ZipFile(str(out))
    body = _epub_text(zf)

    # -- gate 1: no false headings in the content or the navigation ----
    headings = re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", body, re.S)
    heading_texts = [re.sub(r"<[^>]+>", "", t).strip() for _, t in headings]
    for frag in FALSE_HEADING_FRAGMENTS:
        for h in heading_texts:
            assert frag not in h, (frag, h)
    assert "Your Story Book" in " | ".join(heading_texts)
    nav = next(n for n in zf.namelist() if n.endswith("nav.xhtml"))
    nav_text = zf.read(nav).decode("utf-8")
    for frag in FALSE_HEADING_FRAGMENTS:
        assert frag not in nav_text, frag

    # -- gate 2: narrative is not wrapped in <strong> ------------------
    for chapter in (n for n in zf.namelist() if "chapter_" in n):
        text = zf.read(chapter).decode("utf-8")
        assert "<strong>" not in text, chapter

    # -- gate 3: wrapped sentences survive as single paragraphs --------
    # (these strings only exist when cross-block lines merged)
    assert "mom and dad. They ran to the house" in re.sub(
        r"<[^>]+>", "", body
    )

    # -- gate 4: no mask artifacts, transparency preserved --------------
    media = sorted(n for n in zf.namelist() if re.search(r"\.(png|jpe?g|gif)$", n))
    sizes = set()
    alpha_pngs = 0
    import pymupdf  # noqa: F401  (engine dependency, always available)

    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    for name in media:
        pix = fitz.Pixmap(zf.read(name))
        sizes.add((pix.width, pix.height))
        if pix.alpha:
            alpha_pngs += 1
    # the 828x335 grayscale soft-mask raster must not be packaged
    assert (828, 335) not in sizes
    # the five /SMask'd illustrations composite to alpha-carrying PNGs
    assert alpha_pngs >= 5, f"expected >=5 alpha PNGs, got {alpha_pngs}"
    # 39 assets before -> 35 real figures after artifact filtering
    assert len(media) == 35, sorted(media)

    # -- honest record (not a success criterion) -----------------------
    build = result["build"]
    print(
        f"\nflower-garden metrics: chapters={len(build.chapters)} "
        f"welds={build.welded_pairs} assets={len(media)} "
        f"alpha_pngs={alpha_pngs} headings={len(heading_texts)}"
    )


def test_flower_garden_round_2_publication_gates(tmp_path):
    """Round 2: the publication metadata must come from evidence, the
    cover must be designated honestly, and accessibility claims must
    match what the book actually contains."""
    import xml.etree.ElementTree as ET

    result, out = _convert(tmp_path)
    assert result["success"] is True, result
    zf = zipfile.ZipFile(str(out))
    opf_name = next(n for n in zf.namelist() if n.endswith(".opf"))
    opf_xml = zf.read(opf_name).decode("utf-8")

    # -- WS-1: metadata recovered from real evidence -------------------
    # title from the filename tier (the cover title is raster art with
    # no text layer), author from the page-0 byline, language from the
    # PDF catalog /Lang -- none of them sentinels or guesses.
    assert "<dc:title>The Flower Garden</dc:title>" in opf_xml
    assert "T. Albert" in opf_xml
    assert "en-GB" in opf_xml

    # -- WS-2: the title-page illustration is the cover ----------------
    assert 'properties="cover-image"' in opf_xml

    # -- WS-4: no unsupported conformance claim; package language ------
    assert "conformsTo" not in opf_xml
    assert "WCAG" not in opf_xml
    root = ET.fromstring(opf_xml.encode("utf-8"))
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en-GB"
    nav_name = next(n for n in zf.namelist() if n.endswith("nav.xhtml"))
    title_match = re.search(r"<title>(.*?)</title>", zf.read(nav_name).decode("utf-8"), re.S)
    assert title_match and title_match.group(1).strip()

    # -- WS-3: honest description-quality accounting -------------------
    # This book's illustrations carry no captions: every alt text is a
    # location-only stub, so the alternativeText feature must not be
    # claimed and the summary must say so.
    build = result["build"]
    assert build.a11y.image_count >= 30
    assert build.a11y.images_location_only == build.a11y.image_count
    assert build.a11y.images_described == 0
    assert "alternativeText" not in opf_xml
    assert "location-only" in opf_xml


def test_flower_garden_epubcheck(tmp_path):
    """Runs only when epubcheck is installed; skips honestly otherwise."""
    from pdf2epub.engine import packaging_and_validation as pk

    if pk.resolve_tool("epubcheck") is None:
        pytest.skip("epubcheck not installed; conformance not run")
    result, out = _convert(tmp_path)
    assert result["success"] is True
    validator = pk.DualValidator()
    report = validator.validate(str(out), enabled=("epubcheck",))
    assert report.epubcheck_passed, (
        report.epubcheck_errors,
        report.raw_logs,
    )
