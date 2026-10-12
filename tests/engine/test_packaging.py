"""Module 4: reassembly, segmentation, metadata honesty, validation parsing."""

import json
import re
import zipfile
import xml.etree.ElementTree as ET
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


def test_chapter_titles_unescape_entities_exactly_once():
    # The stream is escaped XHTML ("&"); nav/NCX/chapter titles are
    # re-escaped by ebooklib on serialisation, so segmentation must
    # unescape exactly once -- or every "&" in a heading renders as
    # "&amp;" in the navigation (Phase M verification defect).
    stream = [
        heading("<h1>Netflix &amp; TV</h1>", 1, 0, 90.0),
        para("a", 0, 120.0),
    ]
    chapters = pk.segment_chapters(stream)
    assert [t for t, _ in chapters] == ["Netflix & TV"]


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


def _image_element(alt="A figure", alt_source="caption"):
    img = ImageElement(
        ext="png", mime_type="image/png", image_bytes=b"\x89PNG\r\n\x1a\n",
        bbox=(54.0, 200.0, 200.0, 320.0), page_num=0, block_id=2,
        alt_text=alt, filename="img_p0001_b2.png", alt_source=alt_source,
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
        nav = next(n for n in zf.namelist() if n.endswith("nav.xhtml"))
        nav_xml = zf.read(nav).decode()
    assert "structuralNavigation" in xml
    assert "tableOfContents" in xml
    assert "alternativeText" not in xml  # no images: nothing to describe
    # Round 2 decision: no conformance claim is emitted at all. The tool
    # has never run a WCAG audit, so an EPUB Accessibility 1.1 / WCAG AA
    # declaration would be an unsupported claim (dcterms:conformsTo).
    assert "conformsTo" not in xml
    assert "WCAG" not in xml
    # Round 2: the package element must declare its language (Ace's
    # epub-lang check, serious, demands xml:lang on <package>).
    root = ET.fromstring(xml.encode())
    assert root.tag.endswith("package")
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "und"
    # Round 2: the navigation document carries a real <title>, not an
    # empty one (best practice; reading systems show it in the UI).
    title_text = re.search(r"<title>(.*?)</title>", nav_xml, re.S)
    assert title_text and title_text.group(1).strip()


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
# Round 2 WS-3: description-quality honesty
# ---------------------------------------------------------------------------


def test_location_only_stubs_never_earn_the_alt_text_feature(tmp_path):
    """A location stub ("Figure on page N, block M") names where to
    look, not what is there: it is not a text alternative. The OPF
    must not claim alternativeText for it and the summary must say
    exactly what the descriptions are."""
    stream = [
        heading("One"),
        _image_element(alt="Figure on page 1, block 2", alt_source="location"),
        _image_element(alt="Page 3 (image-only page)", alt_source="location"),
    ]
    profile = pk.analyse_accessibility(stream)
    assert profile.image_count == 2
    assert profile.images_described == 0
    assert profile.images_location_only == 2
    assert profile.has_alt_text is False
    out = tmp_path / "stubs.epub"
    pk.build_epub_publication(stream, str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "alternativeText" not in xml
    assert "location-only" in xml


def test_caption_and_stub_counts_are_reported_separately(tmp_path):
    stream = [
        heading("One"),
        _image_element(),  # caption-derived by default
        _image_element(alt="Figure on page 1, block 2", alt_source="location"),
    ]
    profile = pk.analyse_accessibility(stream)
    assert profile.images_described == 1
    assert profile.images_location_only == 1
    assert profile.has_alt_text is False
    assert "1 of 2 images" in profile.summary
    out = tmp_path / "mixed.epub"
    pk.build_epub_publication(stream, str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "alternativeText" not in xml


def test_all_captioned_images_earn_the_alt_text_feature(tmp_path):
    stream = [heading("One"), _image_element(), _image_element(alt="Another caption")]
    profile = pk.analyse_accessibility(stream)
    assert profile.has_alt_text is True
    out = tmp_path / "captioned.epub"
    pk.build_epub_publication(stream, str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "alternativeText" in xml
    assert "All images carry alternative text" in xml


# ---------------------------------------------------------------------------
# Round 2 WS-4: package language declaration
# ---------------------------------------------------------------------------


def test_package_xml_lang_matches_the_publication_language(tmp_path):
    out = tmp_path / "lang.epub"
    pk.build_epub_publication(
        [heading("One"), para("body")], str(out), language="en-GB"
    )
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    root = ET.fromstring(xml.encode())
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en-GB"
    assert "en-GB" in xml  # dc:language agrees with the package attribute


def test_xml_lang_rewrite_preserves_the_container(tmp_path):
    """The OPF rewrite must not damage the EPUB container: mimetype
    stays first and stored, container.xml survives, the OPF parses."""
    out = tmp_path / "zip.epub"
    pk.build_epub_publication([para("x")], str(out), language="de")
    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in zf.namelist()
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        root = ET.fromstring(zf.read(opf))
        assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "de"


# ---------------------------------------------------------------------------
# Round 2 WS-2: cover designation
# ---------------------------------------------------------------------------


def test_cover_image_property_is_emitted_for_the_designated_asset(tmp_path):
    out = tmp_path / "cover.epub"
    pk.build_epub_publication(
        [heading("One"), _image_element()], str(out), cover_image="img_p0001_b2.png"
    )
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
        names = zf.namelist()
    assert 'properties="cover-image"' in xml
    item = re.search(r"<item[^>]*cover-image[^>]*/>", xml)
    assert "img_p0001_b2.png" in item.group(0)
    assert "EPUB/images/img_p0001_b2.png" in names


def test_no_cover_property_without_a_designated_cover(tmp_path):
    out = tmp_path / "nocover.epub"
    pk.build_epub_publication([heading("One"), _image_element()], str(out))
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "cover-image" not in xml


def test_designated_cover_absent_from_the_stream_is_ignored(tmp_path):
    out = tmp_path / "gone.epub"
    pk.build_epub_publication(
        [heading("One"), _image_element()], str(out), cover_image="no_such.png"
    )
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
    assert "cover-image" not in xml


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

    # Same seam as the end-to-end test: absence means the resolution
    # path returns None, not a failed subprocess spawn.
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
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


def test_stylesheet_supports_reflow_and_never_breaks_pages():
    css = pk.DEFAULT_CSS
    # a reflowable EPUB never forces fixed-page breaks (remediation Fix 3)
    for banned in ("page-break", "break-before", "break-after", "break-inside"):
        assert banned not in css
    # every semantic structure the pipeline emits has presentation rules
    for needed in ("ul, ol", "li ", "h4", "h5, h6", "thead", "a {"):
        assert needed in css


def test_structure_metrics_count_what_was_emitted(tmp_path):
    stream = [
        heading("One"),
        para("body"),
        StreamElement(
            ElementType.BLOCK, "ol",
            '<li>first</li><li>second<ul><li>sub</li></ul></li>',
        ),
        StreamElement(
            ElementType.BLOCK, "table", "<tr><td>cell</td></tr>"
        ),
    ]
    out = tmp_path / "metrics.epub"
    build = pk.build_epub_publication(stream, str(out))
    m = build.metrics
    assert m.headings == 1
    assert m.lists == 1
    assert m.list_items == 3  # nested sub items count
    assert m.tables == 1
    assert m.chapters == 1
    assert m.empty_chapters == 0
    assert m.empty_paragraphs == 0
    assert m.unresolved_nav_targets == 0


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


def test_weld_keeps_a_url_hyphen_across_the_page_seam():
    # The cross-page twin: a URL's own hyphen at a page break is slug
    # content, never a soft hyphen to strip.
    left = para("See https://www.kaggle.com/datasets/shivamb/netflix-", 0, 600.0)
    right = para("shows for the catalogue.", 1, 90.0)
    clean, _, welds = pk.process_element_stream([left, right], HEIGHTS)
    assert welds == 1
    assert "netflix-shows" in clean[0].content
    assert "netflixshows" not in clean[0].content


# ---------------------------------------------------------------------------
# Furniture on mixed-tier documents (corpus session 3)
# ---------------------------------------------------------------------------


def test_running_furniture_frequency_counts_positionable_pages():
    """Tier-2 pages carry synthetic bboxes: their furniture is real in
    the text but invisible to position evidence. The frequency gate
    must count pages that COULD show evidence, or running headers leak
    on every mixed-tier document (57/97 = 59% failed the 60% gate on
    the real corpus)."""
    stream = []
    # four positionable pages carrying the running header in the band
    for page in range(4):
        stream.append(para("The Running Header", page, y=30.0))
        stream.append(para("body prose fills the page here", page, y=200.0))
    # five positionless pages (synthetic bboxes): same header, no evidence
    for page in range(4, 9):
        stream.append(
            StreamElement(
                ElementType.PARAGRAPH, "p", "The Running Header",
                bbox=(0.0, 0.0, 0.0, 0.0), page_num=page,
            )
        )
    heights = {i: 680.0 for i in range(9)}
    furniture = pk.detect_running_furniture(stream, heights)
    assert "the running header" in furniture


def test_orphan_page_number_accepts_page_prefix():
    """The M2 corpus shape: 'Page 30' is a page number, not a sentence,
    and must be removed from positionable pages exactly like bare
    digits."""
    stream = [
        para("Some body prose starts the page", 0, y=200.0),
        para("Page 30", 0, y=655.0),
    ]
    clean, furniture, welds = pk.process_element_stream(stream, HEIGHTS)
    assert furniture == []  # single page: no frequency furniture, only orphans
    assert all("Page 30" not in e.content for e in clean)
    assert len(clean) == 1


def test_magazine_fixture_strips_furniture_and_page_numbers(tmp_path):
    """End-to-end for the magazine-with-furniture class: the running
    header is stripped by frequency, 'Page N' is never promoted to a
    heading and never survives as content, and body prose is intact."""
    import make_fixtures as mf

    out = tmp_path / "mag.epub"
    build = pk.build_epub_publication(
        _fixture_stream(mf.build_magazine_furniture_doc(str(out) + ".pdf")),
        str(out),
        title="Magazine Fixture",
        page_heights={i: 680.0 for i in range(6)},
    )
    assert "sample magazine section" in build.stripped_furniture
    import zipfile

    with zipfile.ZipFile(out) as zf:
        body = "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml") and "nav" not in n
        )
    import re

    assert not re.search(r"<h[1-6][^>]*>\s*Page \d+", body)
    assert "Page 3" not in re.sub(r"<[^>]+>", "", body)
    assert "paying reader" in body  # prose intact


def _fixture_stream(pdf_path):
    import fitz

    import pdf2epub.engine.tier1_classifier as t1

    doc = fitz.open(pdf_path)
    profile = t1.DocumentFontProfile.build(doc)
    stream = []
    for i in range(doc.page_count):
        stream.extend(t1.build_page_stream(doc[i], profile, i))
    doc.close()
    return stream
