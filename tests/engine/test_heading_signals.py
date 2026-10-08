"""Phase K: deterministic multi-signal structural heading detection.

Unit tests pin each guard against the false-positive class it exists
for (stabilization plan, Phase 15); fixture tests pin the promoted and
the rejected lines on a document whose headings carry no font-size
signal at all; end-to-end tests pin that promotion survives into
chapters/navigation and that a promoted running header is still
removed by the cross-page furniture filter.
"""

import zipfile

import fitz
import pytest

from pdf2epub.engine import tier1_classifier as t1
from pdf2epub.engine import tier2_llm_handler as t2
from pdf2epub.engine.heading_signals import (
    has_side_by_side_neighbour,
    in_table_region,
    looks_like_table_row,
    structural_heading_level,
    table_neighbourhood_gaps,
    table_region,
)


# ---------------------------------------------------------------------------
# The text/typography decision
# ---------------------------------------------------------------------------


def test_title_shaped_body_size_lines_promote_to_h4():
    assert structural_heading_level("Objective", size=10, body_size=10) == 4
    assert (
        structural_heading_level("Netflix Movies & TV Shows Analysis", size=10, body_size=10)
        == 4
    )
    # small words do not break Title Case
    assert (
        structural_heading_level("Part 1 — Load and Explore (Statistics)", size=10, body_size=10)
        == 4
    )
    # a lone bold line carries no case evidence but bold is enough
    assert structural_heading_level("installation notes", size=10, body_size=10, bold=True) == 4


@pytest.mark.parametrize(
    "text",
    [
        "• Name: Kaggle",                        # bullet art
        "- Fill missing country values",         # ascii bullet
        "1. Count of Movies vs TV Shows",        # numeric enumerator
        "11. Quit",                              # two-digit enumerator
        "a. Nested point",                       # letter enumerator
        "IV. Deeper still",                       # roman enumerator
        "Figure 1. A rendered test square.",     # caption + sentence end
        "Table 2. Baseline results",              # caption marker
        "Source: Kaggle",                         # caption marker with colon
        "Read this now.",                         # short emphasized sentence
        "Search keyword, then continue",          # trailing comma is prose
        "the text continues here",                # no case evidence
        "MultinomialNB(alpha=0.5)",               # lone code-shaped token
        "train_test_split(test_size=0.2)",        # identifier with arguments
    ],
)
def test_prose_and_list_shapes_stay_paragraphs(text):
    assert structural_heading_level(text, size=10, body_size=10) is None


def test_length_and_ratio_limits():
    long = "A Single Heading Crafted To Be Longer Than Seventy-Two Characters Exactly"
    assert len(long) > 72
    assert structural_heading_level(long, size=10, body_size=10) is None
    words = "One Two Three Four Five Six Seven Eight Nine"
    assert len(words.split()) > 8
    assert structural_heading_level(words, size=10, body_size=10) is None
    # only the residual band around body size is decided here
    assert structural_heading_level("Bigger Heading", size=16, body_size=10) is None
    assert structural_heading_level("Tiny Heading", size=8, body_size=10) is None


# ---------------------------------------------------------------------------
# The geometry guards
# ---------------------------------------------------------------------------


def test_table_overlap_gaps():
    assert looks_like_table_row([12.4, 16.6, -4.9])
    assert not looks_like_table_row([12.4, 16.6, 12.5])
    # a huge negative gap is a reading-order jump (footer -> body), not overlap
    assert not looks_like_table_row([-578.1], overlap_limit=55.5)
    assert looks_like_table_row([-32.4], overlap_limit=55.5)


def test_neighbourhood_gaps_follow_the_line_sequence():
    bboxes = [(0, 0, 50, 10), (0, 20, 50, 30), (0, 40, 50, 50)]
    # first entry has no own gap: next two gaps only
    assert table_neighbourhood_gaps(bboxes, 0) == [10.0, 10.0]
    assert table_neighbourhood_gaps(bboxes, 1) == [10.0, 10.0]
    assert table_neighbourhood_gaps(bboxes, 2) == [10.0]


def test_side_by_side_detection():
    same_y = [(54, 100, 130, 111), (200, 100, 340, 111)]
    assert has_side_by_side_neighbour(same_y, 0, size=10)
    stacked = [(54, 100, 130, 111), (54, 114, 130, 125)]
    assert not has_side_by_side_neighbour(stacked, 0, size=10)
    overlapping_x = [(54, 100, 300, 111), (200, 100, 340, 111)]
    assert not has_side_by_side_neighbour(overlapping_x, 0, size=10)


def test_table_region_absorbs_a_header_row_within_one_line_height():
    # three same-baseline cell pairs = evidence
    bboxes = [
        (54, 92.5, 130, 101.5),   # "Field Value" header row
        (54, 112.5, 130, 121.5),  # row 1 left
        (200, 112.5, 340, 121.5),  # row 1 right
        (54, 132.5, 130, 141.5),  # row 2 left
        (200, 132.5, 340, 141.5),  # row 2 right
    ]
    sizes = [10.0] * 5
    region = table_region(bboxes, sizes, pad=14.0)
    assert region is not None
    assert in_table_region(region, bboxes[0])       # within one line height above
    assert not in_table_region(region, (54, 60.0, 130, 71.0))  # well above


# ---------------------------------------------------------------------------
# Tier 1: the structural fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def structural_lines(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["structural_headings"])
    profile = t1.DocumentFontProfile.build(doc)
    lines = [ln for page in doc for ln in t1.classify_page(page, profile)]
    doc.close()
    return lines


def _tags(lines, text):
    return [ln.tag for ln in lines if ln.raw_text.strip() == text]


def test_fixture_promotes_the_real_headings(structural_lines):
    assert _tags(structural_lines, "Artificial Intelligence") == ["h4"]
    # page 1's "Dataset" heading promotes; page 2's identical table cell
    # with the same text must not -- same words, different geometry
    assert sorted(_tags(structural_lines, "Dataset")) == ["h4", "p"]
    assert _tags(structural_lines, "Project Title") == ["h4"]
    assert _tags(structural_lines, "Objective") == ["h4"]


def test_fixture_rejects_the_false_positive_classes(structural_lines):
    # menu items and bullets: list markers
    assert _tags(structural_lines, "1. Count of Movies vs TV Shows") == ["p"]
    assert _tags(structural_lines, "11. Quit") == ["p"]
    assert _tags(structural_lines, "- Fill missing country values with Unknown.") == ["p"]
    # short bold sentence with terminal punctuation
    assert _tags(structural_lines, "This fragment matters deeply.") == ["p"]
    # table header row and every cell shape, including the merged row
    assert _tags(structural_lines, "Field Value") == ["p"]
    assert _tags(structural_lines, "Platform") == ["p"]
    assert _tags(structural_lines, "Fifty Thousand") == ["p"]
    assert _tags(structural_lines, "License Free For Research") == ["p"]


# ---------------------------------------------------------------------------
# Tier 2: the offline digest fallback applies the same decision
# ---------------------------------------------------------------------------


def _digest_line(line_id, block_id, bbox, text, size=10.0, bold=False):
    return {
        "line_id": line_id,
        "block_id": block_id,
        "bbox": bbox,
        "size": size,
        "bold": bold,
        "italic": False,
        "text": text,
    }


def test_digest_fallback_promotes_single_line_headings():
    digest = [
        _digest_line(1, 1, (54.0, 90.0, 200.0, 104.0), "Major Project"),
        _digest_line(2, 2, (54.0, 120.0, 300.0, 134.0), "Build a classifier on real reviews."),
        _digest_line(3, 3, (54.0, 160.0, 120.0, 174.0), "Dataset"),
        _digest_line(4, 3, (200.0, 160.0, 340.0, 174.0), "IMDB Dataset of 50K Reviews"),
    ]
    xhtml = t2._digest_fallback(
        t2.Tier2Request(page_num=1, layout_digest=digest, page_width=420.0)
    )
    assert "<h4>Major Project</h4>" in xhtml
    assert "<p>Build a classifier" in xhtml
    # side-by-side cells are table geometry, never headings
    assert "<h4>Dataset</h4>" not in xhtml
    assert "<p>Dataset</p>" in xhtml


def test_digest_fallback_keeps_merged_paragraphs_as_prose():
    # two digest lines that merge into one wrapped paragraph (same block,
    # one line height apart, ending at the block margin) are not headings
    digest = [
        _digest_line(1, 1, (54.0, 90.0, 260.0, 104.0), "Objective"),
        _digest_line(2, 2, (54.0, 120.0, 258.0, 134.0), "This line wraps at the margin and"),
        _digest_line(3, 2, (54.0, 134.0, 200.0, 148.0), "continues onto the next line."),
    ]
    xhtml = t2._digest_fallback(
        t2.Tier2Request(page_num=1, layout_digest=digest, page_width=420.0)
    )
    assert "<h4>Objective</h4>" in xhtml
    assert xhtml.count("<p>This line wraps at the margin and continues") == 1


# ---------------------------------------------------------------------------
# End to end: chapters, navigation, and the running-header edge case
# ---------------------------------------------------------------------------


def _run(pdf, out, **kw):
    from pdf2epub.engine import driver

    kw.setdefault("llm_adapter", None)
    kw.setdefault("verbose", False)
    kw.setdefault("cache_dir", str(out.parent / "cache"))
    return driver.run_pipeline(str(pdf), str(out), **kw)


def _body(out):
    with zipfile.ZipFile(out) as zf:
        return "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml")
        )


def test_structural_fixture_end_to_end(fixture_pdfs, tmp_path):
    out = tmp_path / "structural.epub"
    result = _run(fixture_pdfs["structural_headings"], out)
    assert result["success"] is True
    build = result["build"]
    assert build.a11y.heading_count >= 4
    # Remediation Fix 2: no clearly major section means one reflowable
    # chapter named by its opening heading -- never one XHTML per h4.
    assert len(build.chapters) == 1
    assert build.chapters[0].title == "Artificial Intelligence"
    body = _body(out)
    for heading in ("Artificial Intelligence", "Dataset", "Project Title", "Objective"):
        assert f">{heading}<" in body
    assert "Field Value" in body and "<h4>Field Value</h4>" not in body
    # list shapes stay prose
    assert "1. Count of Movies vs TV Shows" in body


def test_promoted_running_header_is_stripped_as_furniture(fixture_pdfs, tmp_path):
    out = tmp_path / "rh.epub"
    result = _run(fixture_pdfs["running_header"], out)
    assert result["success"] is True
    build = result["build"]
    # promoted on every page at classify time, removed before packaging:
    # a repeated page-top line must not survive as a swarm of headings
    assert "running header text" in build.stripped_furniture
    assert "Running Header Text" not in _body(out)
    assert build.a11y.heading_count == 0
