"""Module 4: reassembly, segmentation, metadata honesty, validation parsing."""

import json
import zipfile
from pathlib import Path

import pytest
from ebooklib import epub

from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.engine.tier1_classifier import ElementType, ImageElement, StreamElement

PAGE_H = 680.0


def para(text, page=0, y=200.0, block=1):
    return StreamElement(
        element_type=ElementType.PARAGRAPH, tag="p", content=text,
        bbox=(54.0, y, 314.0, y + 12), page_num=page, block_id=block,
    )


def heading(text, level=1, page=0, y=90.0):
    return StreamElement(
        element_type=ElementType.HEADING, tag=f"h{level}", content=text,
        bbox=(54.0, y, 314.0, y + 20), page_num=page, block_id=0, level=level,
    )


def furniture(text, page, y):
    return StreamElement(
        element_type=ElementType.SMALL_TEXT, tag="p", content=text,
        bbox=(54.0, y, 200.0, y + 10), page_num=page, block_id=0, css_class="small",
    )


HEIGHTS = {i: PAGE_H for i in range(10)}


# ---------------------------------------------------------------------------
# Running furniture
# ---------------------------------------------------------------------------


def test_running_header_is_stripped():
    stream = []
    for p in range(5):
        stream.append(furniture("A Test Publication", p, 30.0))
        stream.append(para(f"Body of page {p}", p, 200.0))
    clean, stripped, _ = pk.process_element_stream(stream, HEIGHTS)
    assert "a test publication" in stripped
    assert all("Test Publication" not in e.content for e in clean)
    assert len(clean) == 5


def test_text_appearing_on_few_pages_is_kept():
    stream = []
    for p in range(5):
        stream.append(para(f"Body of page {p}", p, 200.0))
    stream.append(furniture("Only here once", 0, 30.0))
    clean, stripped, _ = pk.process_element_stream(stream, HEIGHTS)
    assert stripped == []
    assert any("Only here once" in e.content for e in clean)


def test_mid_page_repetition_is_not_treated_as_furniture():
    """A refrain in the body must survive; only the band counts."""
    stream = []
    for p in range(5):
        stream.append(para("And so it goes.", p, 300.0))
    clean, stripped, _ = pk.process_element_stream(stream, HEIGHTS)
    assert stripped == []
    assert len(clean) == 5


def test_orphan_page_numbers_are_removed():
    stream = [para("Body text of the page", 0, 200.0), furniture("17", 0, 650.0)]
    clean, _, _ = pk.process_element_stream(stream, HEIGHTS)
    assert len(clean) == 1


def test_a_number_in_the_body_is_not_removed():
    stream = [furniture("1997", 0, 300.0), para("Body text", 0, 320.0)]
    clean, _, _ = pk.process_element_stream(stream, HEIGHTS)
    assert len(clean) == 2


def test_tier2_elements_with_synthetic_bboxes_are_never_stripped():
    """Tier 2 nodes have no spatial data; they must not be guessed at."""
    stream = [
        StreamElement(ElementType.PARAGRAPH, "p", "42", page_num=p, block_id=0)
        for p in range(5)
    ]
    clean, stripped, _ = pk.process_element_stream(stream, HEIGHTS)
    assert stripped == []
    assert len(clean) == 5


# ---------------------------------------------------------------------------
# Cross-page welding
# ---------------------------------------------------------------------------


def test_paragraph_is_welded_across_a_page_seam():
    stream = [
        para("a sentence that continues", 0, 600.0),
        para("onto the following page.", 1, 90.0),
    ]
    clean, _, welds = pk.process_element_stream(stream, HEIGHTS)
    assert welds == 1
    assert len(clean) == 1
    assert clean[0].content == "a sentence that continues onto the following page."


def test_no_weld_after_terminal_punctuation():
    stream = [para("A finished sentence.", 0, 600.0), para("another start", 1, 90.0)]
    clean, _, welds = pk.process_element_stream(stream, HEIGHTS)
    assert welds == 0
    assert len(clean) == 2


def test_no_weld_before_a_capitalised_start():
    stream = [para("ends without punctuation", 0, 600.0), para("New Sentence", 1, 90.0)]
    clean, _, welds = pk.process_element_stream(stream, HEIGHTS)
    assert welds == 0


def test_hyphen_at_the_page_seam_is_rejoined():
    stream = [para("a bro-", 0, 600.0), para("ken word", 1, 90.0)]
    clean, _, welds = pk.process_element_stream(stream, HEIGHTS)
    assert welds == 1
    assert clean[0].content == "a broken word"


def test_headings_are_never_welded_into_paragraphs():
    stream = [para("no terminal punctuation", 0, 600.0), heading("Chapter Two", 1, 1, 90.0)]
    clean, _, welds = pk.process_element_stream(stream, HEIGHTS)
    assert welds == 0
    assert len(clean) == 2


# ---------------------------------------------------------------------------
# Chapter segmentation
# ---------------------------------------------------------------------------


def test_chapters_split_at_the_shallowest_heading_level():
    stream = [
        heading("One", 1, 0, 90.0), para("a", 0, 120.0),
        heading("1.1", 2, 0, 200.0), para("b", 0, 220.0),
        heading("Two", 1, 1, 90.0), para("c", 1, 120.0),
    ]
    chapters = pk.segment_chapters(stream)
    assert [t for t, _ in chapters] == ["One", "Two"]
    assert len(chapters[0][1]) == 4


def test_documents_with_only_h2_split_on_h2():
    stream = [heading("A", 2, 0, 90.0), para("x", 0), heading("B", 2, 1, 90.0)]
    assert [t for t, _ in pk.segment_chapters(stream)] == ["A", "B"]


def test_document_without_headings_becomes_one_chapter():
    stream = [para("x", 0), para("y", 1)]
    chapters = pk.segment_chapters(stream)
    assert len(chapters) == 1
    assert chapters[0][0] == "Front Matter"


def test_content_before_the_first_heading_is_kept():
    stream = [para("preface", 0, 90.0), heading("One", 1, 0, 120.0), para("body", 0, 150.0)]
    chapters = pk.segment_chapters(stream)
    assert len(chapters) == 2
    assert "preface" in chapters[0][1][0].content


# ---------------------------------------------------------------------------
# Accessibility metadata honesty
# ---------------------------------------------------------------------------


def _image_element(alt="A figure"):
    img = ImageElement(
        ext="png", mime_type="image/png", image_bytes=b"\x89PNG\r\n\x1a\n",
        bbox=(54.0, 200.0, 200.0, 320.0), page_num=0, block_id=2,
        alt_text=alt, filename="img_p0001_b2.png",
    )
    return StreamElement(
        ElementType.IMAGE, "figure", "", bbox=img.bbox, page_num=0,
        block_id=2, image_data=img,
    )


def test_alt_text_is_not_claimed_when_there_are_no_images():
    profile = pk.analyse_accessibility([heading("One"), para("body")])
    assert profile.has_alt_text is False
    assert profile.has_structural_navigation is True
    assert "no images" in profile.summary


def test_alt_text_is_not_claimed_when_one_image_lacks_it():
    stream = [_image_element("A figure"), _image_element("")]
    assert pk.analyse_accessibility(stream).has_alt_text is False


def test_structural_navigation_is_not_claimed_without_headings():
    assert pk.analyse_accessibility([para("body")]).has_structural_navigation is False


def test_data_tables_are_detected_without_claiming_a_table_of_contents():
    table = StreamElement(
        ElementType.BLOCK,
        "table",
        "<tr><td>data</td></tr>",
    )
    profile = pk.analyse_accessibility([table])
    assert profile.has_tables is True
    assert profile.has_table_of_contents is False


def test_table_of_contents_feature_requires_top_level_nav_heading():
    assert pk.analyse_accessibility([heading("Chapter")]).has_table_of_contents is True
    assert pk.analyse_accessibility([para("body")]).has_table_of_contents is False


def test_metadata_only_asserts_present_features(tmp_path):
    out = tmp_path / "noimg.epub"
    pk.build_epub_publication([heading("One"), para("body")], str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "structuralNavigation" in xml
    assert "tableOfContents" in xml
    assert "alternativeText" not in xml
    assert pk.CONFORMS_TO in xml


def test_data_table_does_not_emit_table_of_contents_feature(tmp_path):
    table = StreamElement(
        ElementType.BLOCK,
        "table",
        "<tr><td>data</td></tr>",
    )
    out = tmp_path / "table.epub"
    pk.build_epub_publication([table], str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(name for name in zf.namelist() if name.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "tableOfContents" not in xml


def test_metadata_asserts_alt_text_when_earned(tmp_path):
    out = tmp_path / "img.epub"
    pk.build_epub_publication([heading("One"), _image_element()], str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
        assert "EPUB/images/img_p0001_b2.png" in zf.namelist()
    assert "alternativeText" in xml


# ---------------------------------------------------------------------------
# Packaging mechanics
# ---------------------------------------------------------------------------


def test_relative_href_resolution():
    assert pk.relative_href("XHTML/chapter_001.xhtml", "styles/stylesheet.css") == (
        "../styles/stylesheet.css"
    )
    assert pk.relative_href("nav.xhtml", "styles/stylesheet.css") == (
        "styles/stylesheet.css"
    )


def test_chapter_content_is_not_silently_dropped(tmp_path):
    """Regression: a full XML-declared document made ebooklib emit an empty body."""
    out = tmp_path / "content.epub"
    pk.build_epub_publication([heading("One"), para("Distinctive body sentence.")], str(out))
    book = epub.read_epub(str(out))
    # EpubNav subclasses EpubHtml, so a bare isinstance check matches nav.xhtml
    # first and silently tests the wrong document.
    bodies = b"".join(
        i.get_content()
        for i in book.get_items()
        if isinstance(i, epub.EpubHtml) and not isinstance(i, epub.EpubNav)
    )
    assert b"Distinctive body sentence." in bodies


def test_malformed_stream_content_is_recovered_before_epub_insertion(tmp_path):
    broken = StreamElement(
        ElementType.PARAGRAPH,
        "p",
        "Recover this <strong>important text",
        page_num=0,
    )
    out = tmp_path / "recovered.epub"
    pk.build_epub_publication([broken], str(out))
    with zipfile.ZipFile(out) as zf:
        chapter = next(name for name in zf.namelist() if name.endswith("chapter_001.xhtml"))
        body = zf.read(chapter).decode("utf-8")
    assert "Recover this" in body and "important text" in body


def test_malformed_stream_that_recovers_to_empty_fails_loudly(tmp_path, monkeypatch):
    from pdf2epub.engine import tier2_llm_handler

    broken = StreamElement(ElementType.PARAGRAPH, "p", "broken <strong>body", page_num=0)
    monkeypatch.setattr(tier2_llm_handler, "sanitize_and_validate_xhtml", lambda _body: "")
    with pytest.raises(ValueError, match="emptied a non-empty chapter"):
        pk.build_epub_publication([broken], str(tmp_path / "empty.epub"))


def test_table_blocks_render_with_overflow_wrapper(tmp_path):
    table = StreamElement(
        ElementType.BLOCK,
        "table",
        "<tr><td>wide table data</td></tr>",
    )
    assert table.render() == (
        '<div class="tbl"><table><tr><td>wide table data</td></tr></table></div>'
    )
    assert ".tbl { max-width: 100%; overflow-x: auto; }" in pk.DEFAULT_CSS
    out = tmp_path / "table-wrapper.epub"
    pk.build_epub_publication([table], str(out))
    with zipfile.ZipFile(out) as zf:
        chapter = next(name for name in zf.namelist() if name.endswith("chapter_001.xhtml"))
        body = zf.read(chapter)
        css = zf.read("EPUB/styles/stylesheet.css").decode("utf-8")
    assert b'<div class="tbl"><table>' in body
    assert ".tbl { max-width: 100%; overflow-x: auto; }" in css


def test_mimetype_is_first_and_stored(tmp_path):
    out = tmp_path / "m.epub"
    pk.build_epub_publication([para("x")], str(out))
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist()[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED


def test_build_returns_a_useful_record(tmp_path):
    stream = [
        furniture("Running Head", p, 30.0) for p in range(5)
    ] + [heading("One", 1, 0, 90.0)] + [para(f"body {p}", p, 200.0) for p in range(5)]
    build = pk.build_epub_publication(stream, str(tmp_path / "r.epub"),
                                      page_heights=HEIGHTS)
    assert build.stripped_furniture
    assert build.chapters
    assert build.a11y.heading_count == 1


# ---------------------------------------------------------------------------
# Validator log parsing
# ---------------------------------------------------------------------------


def test_epubcheck_warnings_do_not_fail_the_build(tmp_path, monkeypatch):
    """Regression: len(messages) counted INFO and USAGE as errors."""
    epub_path = tmp_path / "x.epub"
    pk.build_epub_publication([para("x")], str(epub_path))

    report = {
        "messages": [
            {"severity": "INFO", "message": "fine"},
            {"severity": "USAGE", "message": "also fine"},
            {"severity": "WARNING", "message": "not fatal"},
        ]
    }

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(cmd, timeout):
        Path(cmd[cmd.index("--json") + 1]).write_text(json.dumps(report))
        return FakeProc()

    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/fake/epubcheck")
    monkeypatch.setattr(pk, "_run_with_tree_kill", fake_run)
    passed, errors, _, available = pk.DualValidator().run_epubcheck(str(epub_path))
    assert available and passed and errors == 0


def test_epubcheck_errors_do_fail_the_build(tmp_path, monkeypatch):
    epub_path = tmp_path / "x.epub"
    pk.build_epub_publication([para("x")], str(epub_path))
    report = {"messages": [{"severity": "ERROR", "message": "RSC-007"},
                           {"severity": "INFO", "message": "fine"}]}

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(cmd, timeout):
        Path(cmd[cmd.index("--json") + 1]).write_text(json.dumps(report))
        return FakeProc()

    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/fake/epubcheck")
    monkeypatch.setattr(pk, "_run_with_tree_kill", fake_run)
    passed, errors, _, _ = pk.DualValidator().run_epubcheck(str(epub_path))
    assert not passed and errors == 1


def test_missing_validators_degrade_gracefully(tmp_path, monkeypatch):
    epub_path = tmp_path / "x.epub"
    pk.build_epub_publication([para("x")], str(epub_path))

    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(pk.subprocess, "run", missing)
    report = pk.DualValidator().validate(str(epub_path))
    assert report.epubcheck_available is False
    assert report.ace_available is False
    assert report.structural_passed is True
    assert report.passed is True


def test_ace_impact_is_read_from_earl_test():
    """Regression: reading 'severity' made every violation land on 'minor'."""
    data = {
        "assertions": [
            {
                "assertions": [
                    {"earl:test": {"earl:impact": "serious"},
                     "earl:result": {"earl:outcome": "fail"}},
                    {"earl:test": {"earl:impact": "critical"},
                     "earl:result": {"earl:outcome": "fail"}},
                    {"earl:test": {"earl:impact": "minor"},
                     "earl:result": {"earl:outcome": "fail"}},
                ]
            }
        ]
    }
    v = pk.parse_ace_violations(data)
    assert v["serious"] == 1 and v["critical"] == 1 and v["minor"] == 1


def test_ace_impact_alternate_location_is_supported():
    data = {"assertions": [{"assertions": [
        {"earl:result": {"earl:impact": "moderate", "earl:outcome": "fail"}}
    ]}]}
    assert pk.parse_ace_violations(data)["moderate"] == 1


def test_ace_passing_assertions_are_not_counted():
    data = {"assertions": [{"assertions": [
        {"earl:test": {"earl:impact": "serious"},
         "earl:result": {"earl:outcome": "pass"}}
    ]}]}
    assert pk.parse_ace_violations(data)["serious"] == 0


def test_ace_unknown_impact_value_lands_in_minor():
    """A future/unrecognised impact label should degrade, not vanish."""
    data = {"assertions": [{"assertions": [
        {"earl:test": {"earl:impact": "cosmetic"},
         "earl:result": {"earl:outcome": "fail"}}
    ]}]}
    v = pk.parse_ace_violations(data)
    assert v["minor"] == 1
    assert v["critical"] == 0 and v["serious"] == 0 and v["moderate"] == 0


def test_ace_malformed_report_degrades_gracefully():
    """A report missing keys entirely must not raise - schema drift should
    surface as zero violations, not a crash that takes down validation."""
    assert pk.parse_ace_violations({}) == {
        "critical": 0, "serious": 0, "moderate": 0, "minor": 0,
    }
    assert pk.parse_ace_violations({"assertions": None}) == {
        "critical": 0, "serious": 0, "moderate": 0, "minor": 0,
    }


# ---------------------------------------------------------------------------
# Internal structural validator
# ---------------------------------------------------------------------------


def test_internal_check_passes_a_good_book(tmp_path):
    out = tmp_path / "good.epub"
    pk.build_epub_publication([heading("One"), para("body"), _image_element()], str(out))
    errors = [e for e in pk.internal_structure_check(str(out))
              if e["severity"] in ("ERROR", "FATAL")]
    assert errors == []


def test_internal_check_flags_missing_alt_and_broken_refs(tmp_path):
    good = tmp_path / "good.epub"
    pk.build_epub_publication([heading("One"), para("body")], str(good))
    bad = tmp_path / "bad.epub"

    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith("chapter_001.xhtml"):
                data = data.replace(
                    b"</body>",
                    b'<p><img src="images/nope.png"/></p>'
                    b'<p><a href="XHTML/ghost.xhtml">x</a></p></body>',
                )
            dst.writestr(info, data, zipfile.ZIP_STORED
                         if info.filename == "mimetype" else zipfile.ZIP_DEFLATED)

    messages = " ".join(e["message"] for e in pk.internal_structure_check(str(bad)))
    assert "img without alt text" in messages
    assert "broken image reference" in messages
    assert "broken internal link" in messages


def test_internal_check_rejects_a_non_epub(tmp_path):
    junk = tmp_path / "junk.epub"
    junk.write_bytes(b"this is not a zip file")
    errors = pk.internal_structure_check(str(junk))
    assert errors and errors[0]["severity"] == "FATAL"


def test_internal_check_reports_a_missing_file(tmp_path):
    errors = pk.internal_structure_check(str(tmp_path / "absent.epub"))
    assert errors[0]["severity"] == "FATAL"
