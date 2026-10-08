"""Heading role inference and the chapter policy it drives.

Fix 2/7/14 of the post-conversion remediation plan: a semantic heading
is evidence about document structure; a chapter boundary is a packaging
decision. These tests pin the role algorithm per evidence regime, the
container tree of the structural (body-size) regime, and the
chapter/navigation behavior each role implies.
"""

import zipfile

from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.engine.heading_roles import infer_heading_roles
from pdf2epub.engine.tier1_classifier import ElementType, StreamElement


def heading(text, level=1, page=0):
    # content is the *inner* XHTML of the element, per stream convention
    return StreamElement(
        element_type=ElementType.HEADING, tag=f"h{level}", content=text,
        bbox=(54.0, 90.0, 314.0, 110.0), page_num=page, block_id=0,
        level=level,
    )


def para(text, page=0):
    return StreamElement(
        element_type=ElementType.PARAGRAPH, tag="p", content=text,
        bbox=(54.0, 120.0, 314.0, 132.0), page_num=page, block_id=1,
    )


def _depths(stream):
    return [r.depth for r in infer_heading_roles(stream)]


# ---------------------------------------------------------------------------
# Ladder regime: strong size evidence (h1/h2)
# ---------------------------------------------------------------------------


def test_ladder_h1_headings_are_majors_h2_are_minors():
    stream = [
        heading("One", 1), para("a"),
        heading("1.1", 2), para("b"),
        heading("Two", 1), para("c"),
    ]
    assert _depths(stream) == [1, 2, 1]


def test_only_h2_documents_split_at_h2():
    # h2 is still ladder evidence: a real book with h2-only chapters keeps
    # its chapters (pinned behaviour from the previous policy).
    stream = [heading("A", 2), para("x"), heading("B", 2), para("y")]
    assert _depths(stream) == [1, 1]


def test_empty_opening_h1_is_the_document_title():
    stream = [heading("Book Title", 1), heading("Chapter One", 1), para("a")]
    assert _depths(stream) == [0, 1]


def test_opening_h1_with_content_is_a_major_not_a_title():
    stream = [heading("Chapter One", 1), para("prose"), heading("Chapter Two", 1), para("more")]
    assert _depths(stream) == [1, 1]


# ---------------------------------------------------------------------------
# Structural regime: body-size headings, content-mass evidence
# ---------------------------------------------------------------------------


def test_structural_regime_builds_the_container_tree():
    # The six-page pattern: a bare title label, a section label with
    # content-bearing leaves under it, a page-break sibling section,
    # and a nested label under that.
    stream = [
        heading("Artificial Intelligence", 4, page=0),
        heading("Minor Project", 4, page=0),
        heading("Netflix Movies Analysis", 4, page=0), para("x"),
        heading("Dataset", 4, page=0), para("y"),
        heading("Deliverables", 4, page=1), para("z"),
        heading("Major Project", 4, page=2),
        heading("Minor Project IMDB", 4, page=2),
        heading("Dataset Details", 4, page=2), para("t"),
    ]
    assert _depths(stream) == [0, 1, 2, 2, 2, 1, 2, 3]


def test_a_flat_leaf_document_has_no_fragmentation():
    stream = [heading("Opening", 4), para("a"), heading("Section", 4), para("b")]
    assert _depths(stream) == [1, 2]
    chapters = pk.segment_chapters(stream)
    assert len(chapters) == 1
    assert "Opening" in chapters[0][0]


def test_content_before_the_first_heading_prevents_the_title_role():
    stream = [
        para("intro"),
        heading("One", 4), para("a"),
        heading("Two", 4), para("b"),
    ]
    assert _depths(stream) == [2, 2]


# ---------------------------------------------------------------------------
# Chapter policy
# ---------------------------------------------------------------------------


def test_heading_only_prefix_merges_into_the_first_chapter():
    stream = [heading("Document Title", 4), heading("Chapter One", 4), para("a")]
    chapters = pk.segment_chapters(stream)
    assert [t for t, _ in chapters] == ["Chapter One"]
    assert len(chapters[0][1]) == 3  # the title heading stays visible content


def test_majors_split_and_minors_stay_in_chapter():
    stream = [
        heading("Doc Title", 4),
        heading("Section One", 4),
        heading("Sub One", 4), para("a"),
        heading("Sub Two", 4), para("b"),
        heading("Section Two", 4, page=3),
        heading("Sub Three", 4), para("c"),
    ]
    chapters = pk.segment_chapters(stream)
    assert [t for t, _ in chapters] == ["Section One", "Section Two"]
    # every element survives, in order, in exactly one chapter
    flat = [e for _, els in chapters for e in els]
    assert len(flat) == len(stream)
    assert all(flat[i] is stream[i] for i in range(len(stream)))


def test_documents_without_headings_stay_one_chapter():
    chapters = pk.segment_chapters([para("x"), para("y")])
    assert [t for t, _ in chapters] == ["Front Matter"]


# ---------------------------------------------------------------------------
# Navigation derived from the same stream
# ---------------------------------------------------------------------------


def test_navigation_lists_every_heading_anchor(tmp_path):
    stream = [
        heading("Artificial Intelligence", 4, page=0),
        heading("Minor Project", 4, page=0),
        heading("Netflix Movies Analysis", 4, page=0), para("x"),
        heading("Dataset", 4, page=0), para("y"),
        heading("Major Project", 4, page=2),
        heading("Dataset Details", 4, page=2), para("t"),
    ]
    out = tmp_path / "nav.epub"
    pk.build_epub_publication(stream, str(out), preprocess=False)
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode("utf-8")
    assert "Minor Project</a>" in nav      # chapter entries
    assert "Major Project</a>" in nav
    for probe in ("Artificial Intelligence", "Netflix Movies Analysis",
                  "Dataset", "Dataset Details"):
        assert f">{probe}</a>" in nav       # every heading is reachable
    assert nav.count("#sec") == 4           # 6 headings - 2 chapter entries
