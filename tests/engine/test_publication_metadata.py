"""Round 2 WS-1: publication metadata derivation (title, author, language).

The evidence chains, weakest-last, each tier only consulted when the
stronger tier produced nothing:

* title   -- explicit -> docinfo -> first-page heading -> filename
             evidence -> sentinel.  The filename tier exists because a
             cover title is often *raster art* with no text layer at
             all; the one deterministic place it survives is the file
             name, where it is usually written in caps.
* author  -- explicit -> docinfo -> opening-pages byline -> sentinel.
             ``Published by`` / ``Illustrated by`` lines must never be
             harvested, and a title-case body sentence that merely
             starts with "By" must not become an author: the line must
             be *typographically distinct* from the body profile.
* language -- explicit (BCP-47 validated) -> PDF catalog ``/Lang``
             (BCP-47 validated: real PDFs carry junk there) -> ``und``.
             Never a silent "en" guess: a hardcoded language would lie
             about every non-English document and mispronounce nothing
             honestly.

Every test converts a real (tiny) PDF through the driver and asserts
the packaged OPF, because metadata only exists once ebooklib wrote it.
"""

from pathlib import Path

import pytest
from ebooklib import epub

from pdf2epub.engine import driver

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


PAGE_W, PAGE_H = 420.0, 680.0
BODY_SIZE = 14.0


def _make_pdf(
    path,
    *,
    title="",
    author="",
    lang=None,
    lines=None,
    body="This is ordinary body prose and not a heading at all.",
):
    """A minimal document: optional docinfo, optional catalog /Lang,
    one body line and any extra (text, size, font) lines on page 0."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = 120.0
    if body:
        page.insert_text((54.0, y), body, fontname="helv", fontsize=BODY_SIZE)
        y += 60.0
    for text, size, font in lines or []:
        page.insert_text((54.0, y), text, fontname=font, fontsize=size)
        y += size * 3.0
    if title or author:
        doc.set_metadata({"title": title, "author": author})
    if lang is not None:
        doc.xref_set_key(doc.pdf_catalog(), "Lang", lang)
    doc.save(str(path))
    doc.close()
    return Path(path)


def _convert(pdf, tmp_path, name="out.epub", **kw):
    out = tmp_path / name
    result = driver.run_pipeline(
        str(pdf),
        str(out),
        llm_adapter=None,
        verbose=False,
        cache_dir=str(tmp_path / "cache"),
        **kw,
    )
    assert result["success"] is True, result
    return epub.read_epub(str(out))


def _meta(book, name):
    values = book.get_metadata("DC", name)
    assert values, f"no dc:{name} in the OPF"
    return values[0][0]


# ---------------------------------------------------------------------------
# Title: the filename evidence tier
# ---------------------------------------------------------------------------

FLOWER_NAME = "20250926124047041-THE-FLOWER-GARDEN-Free-Childrens-Book-By-Monkey-Pen.pdf"


def test_filename_evidence_recovers_the_cover_title(tmp_path):
    """The Flower Garden's title lives only in the cover raster; the
    leading uppercase run of the file name is the last deterministic
    witness and must become the dc:title."""
    pdf = _make_pdf(tmp_path / FLOWER_NAME)
    book = _convert(pdf, tmp_path)
    assert _meta(book, "title") == "The Flower Garden"


def test_docinfo_outranks_filename_evidence(tmp_path):
    pdf = _make_pdf(tmp_path / FLOWER_NAME, title="Embedded Title")
    book = _convert(pdf, tmp_path)
    assert _meta(book, "title") == "Embedded Title"


def test_first_page_heading_outranks_filename_evidence(fixture_pdfs, tmp_path):
    from shutil import copy as _copy

    loud_name = "MY-GREAT-BOOK-structural.pdf"
    pdf = tmp_path / loud_name
    _copy(fixture_pdfs["structural_headings"], pdf)
    book = _convert(pdf, tmp_path)
    assert _meta(book, "title") == "Artificial Intelligence"


def test_filename_without_an_uppercase_run_keeps_the_sentinel(tmp_path):
    pdf = _make_pdf(tmp_path / "report final v2.pdf")
    book = _convert(pdf, tmp_path)
    assert _meta(book, "title") == "Untitled Publication"


def test_filename_tier_honours_the_length_cap(tmp_path):
    """A huge all-caps run is a filename dump, not a title."""
    run_of_words = "-".join(f"AAAA{n:02d}" for n in range(22))
    pdf = _make_pdf(tmp_path / f"{run_of_words}.pdf")
    book = _convert(pdf, tmp_path)
    assert _meta(book, "title") == "Untitled Publication"


# ---------------------------------------------------------------------------
# Author: the opening-pages byline tier
# ---------------------------------------------------------------------------


def test_byline_evidence_recovers_the_author(tmp_path):
    pdf = _make_pdf(
        tmp_path / "flower.pdf",
        lines=[("By T. Albert", 10.0, "helv")],
    )
    book = _convert(pdf, tmp_path)
    assert _meta(book, "creator") == "T. Albert"


def test_publisher_lines_are_never_authors(tmp_path):
    pdf = _make_pdf(
        tmp_path / "flower.pdf",
        lines=[("Published by Monkey Pen Ltd", 10.0, "helv")],
    )
    book = _convert(pdf, tmp_path)
    assert _meta(book, "creator") == "Unknown Author"


def test_illustrator_credit_is_never_the_author(tmp_path):
    pdf = _make_pdf(
        tmp_path / "flower.pdf",
        lines=[("By T. Albert", 10.0, "helv"),
               ("Illustrated by: maaillustrations.com", 10.0, "helv")],
    )
    book = _convert(pdf, tmp_path)
    assert _meta(book, "creator") == "T. Albert"


def test_body_text_starting_with_by_is_not_an_author(tmp_path):
    """A title-case sentence in the body font at body size is prose,
    not a credit line; the byline must be typographically distinct."""
    pdf = _make_pdf(
        tmp_path / "flower.pdf",
        body="By The Time They Arrived everything had changed again.",
    )
    book = _convert(pdf, tmp_path)
    assert _meta(book, "creator") == "Unknown Author"


# ---------------------------------------------------------------------------
# Language: the BCP-47 policy
# ---------------------------------------------------------------------------


def test_language_comes_from_the_pdf_catalog(tmp_path):
    pdf = _make_pdf(tmp_path / "flower.pdf", lang="(en-GB)")
    book = _convert(pdf, tmp_path)
    assert _meta(book, "language") == "en-GB"


def test_unknown_language_falls_back_to_und(tmp_path):
    pdf = _make_pdf(tmp_path / "flower.pdf")
    book = _convert(pdf, tmp_path)
    # 'und' (BCP-47 undetermined) -- never a silent "en" guess
    assert _meta(book, "language") == "und"


def test_invalid_catalog_language_is_rejected(tmp_path):
    """Real corpus PDFs carry junk in /Lang (e.g. b'\\xff5'); an
    invalid tag must never reach the OPF."""
    pdf = _make_pdf(tmp_path / "flower.pdf", lang="<FF35>")
    book = _convert(pdf, tmp_path)
    assert _meta(book, "language") == "und"


def test_explicit_language_overrides_all_evidence(tmp_path):
    pdf = _make_pdf(tmp_path / "flower.pdf", lang="(en-GB)")
    book = _convert(pdf, tmp_path, language="fr")
    assert _meta(book, "language") == "fr"


def test_malformed_explicit_language_falls_back_to_evidence(tmp_path):
    """Explicit tags are checked for BCP-47 well-formedness, not IANA
    registry membership (no registry ships with the tool; EPUBCheck
    applies the same well-formedness rule). A malformed tag is
    ignored and the /Lang evidence is used instead."""
    pdf = _make_pdf(tmp_path / "flower.pdf", lang="(en-GB)")
    book = _convert(pdf, tmp_path, language="English Language")
    assert _meta(book, "language") == "en-GB"
