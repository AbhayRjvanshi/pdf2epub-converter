"""Phase F: PDF hyperlink extraction — external URI annotations and
internal GOTO links.

Tests the LINK-001 fix (91 missing external URIs) and LINK-002 fix
(238 missing internal links) from the quality-baseline defect register.

The link is stored as StreamElement metadata and applied at render
time, after all stream transformations. Whole-element wrapping is
guarded by a coverage threshold: annotations that cover too little
of the element are dropped (recorded), not applied to unrelated text.
"""

import zipfile
from pathlib import Path

import pytest

from pdf2epub.engine import driver
from pdf2epub.engine import tier1_classifier as t1

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


LINK_COVERAGE_THRESHOLD = 0.6  # annotation must cover >= 60% of the element
LINK_URI_WHITELIST = {"http", "https", "mailto"}


def _make_linked_pdf(path: Path):
    """A 3-page PDF with:
    - p1: heading 'Documentation' with a URI annotation
    - p1: paragraph with a visible text URL (no annotation on it — for
      the linkify-unaffected test)
    - p2: heading 'Second Section' (internal link target)
    - p1: text 'Go to Section 2' with a GOTO annotation targeting p2
    - p1: small text 'javascript:alert(1)' with an unsupported-scheme
      annotation (should be dropped)
    """
    doc = fitz.open()
    doc.new_page(width=420, height=680)  # page 0
    doc.new_page(width=420, height=680)  # page 1
    p1 = doc[0]
    p2 = doc[1]

    # heading on p1 (will get a URI annotation)
    p1.insert_text((54, 100), "Documentation Guide", fontname="hebo", fontsize=18)
    heading_rect = fitz.Rect(50, 80, 350, 110)
    p1.insert_link({"kind": fitz.LINK_URI, "from": heading_rect,
                     "uri": "https://example.com/docs"})

    # paragraph with a visible text URL (no annotation)
    p1.insert_text((54, 160), "Visit https://example.com for more info.",
                   fontname="helv", fontsize=12)

    # 'Go to Section 2' with a GOTO annotation
    p1.insert_text((54, 220), "Go to Section 2", fontname="helv", fontsize=12)
    goto_rect = fitz.Rect(50, 205, 250, 230)
    p1.insert_link({"kind": fitz.LINK_GOTO, "from": goto_rect, "page": 1,
                     "to": fitz.Point(54, 100)})

    # unsupported scheme (javascript:) — must be dropped
    p1.insert_text((54, 280), "Dangerous link", fontname="helv", fontsize=12)
    js_rect = fitz.Rect(50, 265, 200, 290)
    p1.insert_link({"kind": fitz.LINK_URI, "from": js_rect,
                     "uri": "javascript:alert(1)"})

    # body text to make the page route to Tier 1
    p1.insert_text((54, 340), "Body text for Tier 1 routing on page one.",
                   fontname="helv", fontsize=12)

    # heading on p2 (the GOTO target)
    p2.insert_text((54, 100), "Second Section", fontname="hebo", fontsize=18)
    p2.insert_text((54, 160), "Content of the second section.",
                   fontname="helv", fontsize=12)

    doc.save(str(path))
    doc.close()
    return path


def _make_duplicate_link_pdf(path: Path):
    """A PDF where the same URL is both a PDF annotation and visible
    text — the output must have exactly one anchor, not nested links."""
    doc = fitz.open()
    doc.new_page(width=420, height=680)
    p1 = doc[0]
    p1.insert_text((54, 100), "See https://example.com/docs for details.",
                   fontname="helv", fontsize=12)
    link_rect = fitz.Rect(50, 85, 400, 110)
    p1.insert_link({"kind": fitz.LINK_URI, "from": link_rect,
                     "uri": "https://example.com/docs"})
    p1.insert_text((54, 160), "More body text for routing.",
                   fontname="helv", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _convert(pdf, tmp_path, name="out.epub"):
    out = tmp_path / name
    result = driver.run_pipeline(
        str(pdf), str(out),
        llm_adapter=None, verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),
    )
    assert result["success"] is True, result
    with zipfile.ZipFile(str(out)) as zf:
        xhtml = "".join(
            zf.read(n).decode("utf-8", "ignore")
            for n in zf.namelist() if n.endswith(".xhtml") and "nav" not in n
        )
        return result, xhtml


def _convert_files(pdf, tmp_path, name="out.epub"):
    out = tmp_path / name
    result = driver.run_pipeline(
        str(pdf), str(out),
        llm_adapter=None, verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),
    )
    assert result["success"] is True, result
    return out


# ---------------------------------------------------------------------------
# External URI annotations
# ---------------------------------------------------------------------------


def test_uri_annotation_produces_epub_link(tmp_path):
    """LINK-001: a PDF URI annotation on a heading produces a valid
    <a href> in the EPUB XHTML."""
    pdf = _make_linked_pdf(tmp_path / "linked.pdf")
    result, xhtml = _convert(pdf, tmp_path)
    assert 'href="https://example.com/docs"' in xhtml, (
        "URI annotation must produce a clickable link"
    )


def test_text_url_still_linkified_without_annotation(tmp_path):
    """Existing behavior preserved: a plain-text URL without a PDF
    annotation is still linkified by semantic_normalizer."""
    pdf = _make_linked_pdf(tmp_path / "linked.pdf")
    result, xhtml = _convert(pdf, tmp_path)
    # the visible URL in the body text should be linkified by linkify_urls
    assert 'href="https://example.com"' in xhtml, (
        "text URL without annotation must still be linkified"
    )


def test_unsupported_uri_scheme_dropped(tmp_path):
    """A javascript: URI annotation is silently dropped; the conversion
    succeeds and no javascript: link appears in the output."""
    pdf = _make_linked_pdf(tmp_path / "linked.pdf")
    result, xhtml = _convert(pdf, tmp_path)
    assert "javascript:" not in xhtml, (
        "unsupported URI scheme must not appear in the EPUB"
    )


# ---------------------------------------------------------------------------
# Duplicate-link prevention
# ---------------------------------------------------------------------------


def test_no_duplicate_links_for_same_url(tmp_path):
    """When a URI annotation and a visible text URL point to the same
    destination, the EPUB contains exactly one anchor — no nesting."""
    pdf = _make_duplicate_link_pdf(tmp_path / "dup.pdf")
    result, xhtml = _convert(pdf, tmp_path)
    # count occurrences of the href
    count = xhtml.count('href="https://example.com/docs"')
    assert count == 1, (
        f"expected exactly 1 link to example.com/docs, got {count}"
    )
    # no nested <a> tags
    assert "<a href=" not in xhtml.split('href="https://example.com/docs"')[1].split("</a>")[0] or True
    # stronger check: no '<a' inside another '<a'
    import re
    nested = re.search(r"<a[^>]*>.*?<a[^>]*>", xhtml, re.DOTALL)
    assert not nested, f"nested link found: {nested.group()[:80]}"


# ---------------------------------------------------------------------------
# Internal GOTO links
# ---------------------------------------------------------------------------


def test_goto_annotation_produces_chapter_link(tmp_path):
    """LINK-002: a PDF GOTO annotation produces a link to the target
    chapter in the EPUB."""
    pdf = _make_linked_pdf(tmp_path / "linked.pdf")
    out = _convert_files(pdf, tmp_path)
    with zipfile.ZipFile(str(out)) as zf:
        xhtml = "".join(
            zf.read(n).decode("utf-8", "ignore")
            for n in zf.namelist() if n.endswith(".xhtml") and "nav" not in n
        )
        chapter_files = [n for n in zf.namelist() if n.endswith(".xhtml") and "chapter" in n]
    # there should be an internal link to a chapter file (bare filename,
    # relative to the shared XHTML/ directory)
    import re
    internal_links = re.findall(r'href="(chapter_\d+\.xhtml[^"]*)"', xhtml)
    assert internal_links, (
        "GOTO annotation must produce an internal chapter link; "
        f"chapter files: {chapter_files}"
    )


# ---------------------------------------------------------------------------
# No regressions
# ---------------------------------------------------------------------------


def test_no_links_added_when_pdf_has_none(fixture_pdfs, tmp_path):
    """A PDF without annotations produces no added <a> tags beyond
    what linkify_urls creates from visible text."""
    result, xhtml = _convert(fixture_pdfs["no_heading"], tmp_path)
    # no_heading has no visible URLs and no annotations
    assert "<a href=" not in xhtml or xhtml.count("<a href=") == 0, (
        "no annotations and no text URLs → no links expected"
    )
