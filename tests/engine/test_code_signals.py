"""Fix 9: non-monospace code detection (classification + pipeline).

The contract under test, per the remediation plan's review:

- detection happens BEFORE heading promotion, so title-cased code such
  as ``SELECT Name FROM Users`` never becomes a heading;
- two consecutive strong lines with compatible geometry may qualify;
  three-plus weaker-evidence lines may qualify as a combined run;
- a label strengthens a candidate but never establishes a block alone;
- URL-only lines and list-marker lines never initiate code, sentence-
  shaped prose is never absorbed, and established runs tolerate
  plausible continuations;
- the existing monospace path is untouched;
- reconstructed indentation is verified in the rendered output, not
  just in stored metadata.
"""

import xml.etree.ElementTree as ET
import zipfile

import fitz
import pytest

from pdf2epub.engine import tier1_classifier as t1
from pdf2epub.engine.code_signals import detect_code_lines, line_evidence
from pdf2epub.engine.tier1_classifier import DocumentFontProfile


# ---------------------------------------------------------------------------
# Evidence classification (unit level)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "def convert(path):",                       # keyword statement
        "import numpy as np",
        "return build(doc, html)",
        "if doc.page_count > 0:",
        "result = client.get(url)",                # assignment
        "print(result.status)",                    # call statement
        "SELECT Name FROM Users",                  # SQL keyword
        "WHERE Age > 30;",
        "# process the input and return the total", # comment marker
        "// C-family comment line",
        "}",                                       # block punctuation
        "if (total > 0) {",                        # C-family opener
    ],
)
def test_strong_evidence_shapes(text):
    assert line_evidence(text) == "strong"


@pytest.mark.parametrize(
    "text",
    [
        "https://docs.example.com/convert",        # URL-only line
        "1. Set retries = 5 in the config.",       # list marker + sentence
        "- bullet item with some words",
        "The function returns a structured document.",  # sentence prose
        "Call convert(path) to begin processing.", # mention in a sentence
        "if the result is empty, retry the call.", # prose, despite keyword
        "For more details see the documentation.",
    ],
)
def test_negative_evidence_shapes(text):
    assert line_evidence(text) == "negative"


def test_weak_evidence_shapes():
    assert line_evidence("x = 5,") == "weak"          # trailing comma
    assert line_evidence("total += 1") == "strong"   # augmented assignment
    assert line_evidence("an ordinary sentence without syntax") == "none"


# ---------------------------------------------------------------------------
# Run rules (unit level, synthetic geometry)
# ---------------------------------------------------------------------------


def _line(text, y, x0=54.0, size=10.0, tag="p"):
    return t1.ClassifiedLine(
        text=text, raw_text=text, tag=tag, level=0, monospace=False,
        wrapped=False, bbox=(x0, y, x0 + 200.0, y + 14.0), size=size,
        block_id=1,
    )


def _profile():
    return DocumentFontProfile(
        body_size=10.0, line_height=14.0, main_font="Helvetica"
    )


def _tags(lines):
    return [ln.tag for ln in detect_code_lines(lines, _profile())]


def test_two_strong_aligned_lines_qualify():
    lines = [
        _line("The setup is as follows.", 90.0),
        _line("result = client.get(url)", 120.0),
        _line("print(result.status)", 134.0),
    ]
    assert _tags(lines) == ["p", "pre", "pre"]


def test_one_strong_line_among_prose_never_qualifies():
    lines = [
        _line("Ordinary prose opens the section.", 90.0),
        _line("MultinomialNB(alpha=0.5)", 120.0),
        _line("More ordinary prose follows here.", 134.0),
    ]
    assert _tags(lines) == ["p", "p", "p"]


def test_label_boost_never_establishes_a_block_alone():
    # label + a single strong line is not a block
    lines = [
        _line("Example implementation:", 90.0),
        _line("result = client.get(url)", 104.0),
        _line("Then the prose resumes normally.", 140.0),
    ]
    assert _tags(lines) == ["p", "p", "p"]


def test_label_boost_admits_a_weak_line_into_a_strong_run():
    # label + strong + weak: the boost qualifies the pair (without the
    # label, one strong and one weak line would not qualify)
    lines = [
        _line("Example implementation:", 90.0),
        _line("result = client.get(url)", 104.0),  # strong
        _line("x = 5,", 118.0),                   # weak continuation
    ]
    assert _tags(lines) == ["p", "pre", "pre"]


def test_url_only_line_never_initiates_but_sentence_breaks_runs():
    lines = [
        _line("https://docs.example.com/convert", 90.0),
        _line("result = client.get(url)", 104.0),
        _line("The function returns a structured document.", 140.0),
        _line("print(result.status)", 168.0),
    ]
    # URL cannot start the run; the sentence ends any later geometry
    assert _tags(lines) == ["p", "p", "p", "p"]


def test_list_marker_lines_are_never_absorbed():
    lines = [
        _line("result = client.get(url)", 90.0),
        _line("print(result.status)", 104.0),
        _line("1. Set retries = 5 in the config.", 132.0),
        _line("2. Import the library before use.", 146.0),
    ]
    assert _tags(lines) == ["pre", "pre", "p", "p"]


def test_existing_monospace_pre_lines_pass_through_untouched():
    lines = [
        t1.ClassifiedLine(
            text="already code", raw_text="already code", tag="pre",
            level=0, monospace=True, wrapped=False,
            bbox=(54.0, 90.0, 200.0, 104.0), size=10.0, block_id=1,
        ),
        _line("result = client.get(url)", 118.0),
        _line("print(result.status)", 132.0),
    ]
    assert _tags(lines) == ["pre", "pre", "pre"]


# ---------------------------------------------------------------------------
# Fixture: classification through the real Tier 1 flow
# ---------------------------------------------------------------------------


@pytest.fixture()
def classified(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["proportional_code"])
    profile = t1.DocumentFontProfile.build(doc)
    lines = t1.classify_page(doc[0], profile)
    doc.close()
    return lines


def _tag_of(lines, raw_text):
    matches = [ln for ln in lines if ln.raw_text.strip() == raw_text]
    assert matches, f"line not found: {raw_text!r}"
    return matches[0].tag


def test_python_listing_is_classified_as_code(classified):
    for text in (
        "def convert(path):",
        "doc = open_pdf(path)",
        "if doc.page_count > 0:",
        'html = "<p>Tom & Jerry</p>"',
        "return build(doc, html)",
        "return None",
    ):
        assert _tag_of(classified, text) == "pre", text


def test_sql_run_qualifies_without_a_label_and_never_becomes_a_heading(
    classified,
):
    # the promotion hazard: title-cased SQL must be code, not h4
    assert _tag_of(classified, "SELECT Name FROM Users") == "pre"
    assert _tag_of(classified, "WHERE Age > 30;") == "pre"
    assert not any(ln.tag.startswith("h") for ln in classified)


def test_short_second_listing_qualifies(classified):
    assert _tag_of(classified, "result = client.get(url)") == "pre"
    assert _tag_of(classified, "print(result.status)") == "pre"


def test_negatives_stay_prose(classified):
    for text in (
        "Example implementation:",
        "The function returns a structured document.",
        "Call convert(path) to begin processing.",
        "https://docs.example.com/convert",
        "1. Set retries = 5 in the config.",
        "2. Import the library before use.",
    ):
        assert _tag_of(classified, text) == "p", text


# ---------------------------------------------------------------------------
# Fixture: stream collection and rendered EPUB
# ---------------------------------------------------------------------------


def test_three_code_blocks_with_faithful_indentation(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["proportional_code"])
    profile = t1.DocumentFontProfile.build(doc)
    elements = t1.build_page_stream(doc[0], profile, 0)
    doc.close()
    blocks = [e for e in elements if e.element_type is t1.ElementType.CODE_BLOCK]
    assert len(blocks) == 3
    python = blocks[0].content
    assert python.splitlines()[0] == "def convert(path):"
    assert python.splitlines()[1] == "    doc = open_pdf(path)"
    # content is escaped inner XHTML (the pipeline invariant); the XML
    # parse in the e2e below proves the displayed text is the raw source
    assert (
        python.splitlines()[3]
        == '        html = "&lt;p&gt;Tom &amp; Jerry&lt;/p&gt;"'
    )
    assert "SELECT Name FROM Users" in blocks[2].content
    assert "WHERE Age &gt; 30;" in blocks[2].content
    # no prose absorbed into any block
    for block in blocks:
        assert "retries = 5" not in block.content
        assert "structured document" not in block.content


def test_rendered_epub_structure(fixture_pdfs, tmp_path):
    """Structural assertions on the packaged EPUB (Fix 9 acceptance)."""
    from pdf2epub.engine import driver

    out = tmp_path / "code.epub"
    result = driver.run_pipeline(
        fixture_pdfs["proportional_code"], str(out),
        llm_adapter=None, verbose=False, cache_dir=str(tmp_path / "cache"),
    )
    assert result["success"] is True
    assert result["build"].metrics.code_blocks == 3

    with zipfile.ZipFile(out) as zf:
        chapter = next(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml") and "nav" not in n
        )
    root = ET.fromstring(chapter)
    ns = "{http://www.w3.org/1999/xhtml}"

    pres = root.iter(f"{ns}pre")
    pre_texts = []
    for pre in pres:
        codes = list(pre.iter(f"{ns}code"))
        assert len(codes) == 1, "every pre carries exactly one code child"
        pre_texts.append("".join(codes[0].itertext()))

    assert len(pre_texts) == 3
    # displayed content preserved, escaping invisible after the parse
    assert pre_texts[0].splitlines() == [
        "def convert(path):",
        "    doc = open_pdf(path)",
        "    if doc.page_count > 0:",
        '        html = "<p>Tom & Jerry</p>"',
        "        return build(doc, html)",
        "    return None",
    ]
    assert pre_texts[2] == "SELECT Name FROM Users\nWHERE Age > 30;"

    # the negatives: ordered list, link, and prose all outside the blocks
    ols = list(root.iter(f"{ns}ol"))
    assert ols, "the numbered list survives as a semantic list"
    list_text = "".join(els.text or "" for els in root.iter(f"{ns}li"))
    assert "retries = 5" in list_text
    anchors = [
        a for a in root.iter(f"{ns}a") if a.get("href", "").startswith("http")
    ]
    assert anchors, "the URL became a hyperlink"
    for text in pre_texts:
        assert "retries = 5" not in text
        assert "docs.example.com" not in text
        assert "structured document" not in text
