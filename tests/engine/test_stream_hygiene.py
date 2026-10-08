"""Empty-block elimination and stream hygiene (remediation Fix 13).

Nothing blank reaches the EPUB: empty Tier-2 passthrough blocks and
empty paragraphs die at stream construction, blank content dies at
chapter-body preparation, <br> runs collapse to one separator, and the
internal structural check flags anything that slips through as a
conversion error rather than shipping silent whitespace.
"""

import zipfile
from pathlib import Path

import pytest

from pdf2epub.engine import driver
from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.engine.tier1_classifier import ElementType, StreamElement


# ---------------------------------------------------------------------------
# Tier-2 stream construction drops empties
# ---------------------------------------------------------------------------


def test_empty_passthrough_blocks_are_dropped_but_hr_survives():
    elements = driver.parse_xhtml_to_stream_elements(
        "<table></table><ul></ul><hr/><p>kept</p>", 0
    )
    assert [(e.element_type, e.tag) for e in elements] == [
        (ElementType.BLOCK, "hr"),
        (ElementType.PARAGRAPH, "p"),
    ]


def test_regex_fallback_drops_empty_paragraphs(monkeypatch):
    from lxml import html as lhtml

    def boom(*args, **kwargs):
        raise RuntimeError("no lxml")

    monkeypatch.setattr(lhtml, "fragment_fromstring", boom)
    elements = driver.parse_xhtml_to_stream_elements(
        "<p>kept</p><p>   </p><h1></h1>", 0
    )
    assert [e.tag for e in elements] == ["p"]
    assert elements[0].content == "kept"


# ---------------------------------------------------------------------------
# Chapter body preparation
# ---------------------------------------------------------------------------


def _para(content):
    return StreamElement(
        element_type=ElementType.PARAGRAPH, tag="p", content=content,
        bbox=(54.0, 90.0, 314.0, 102.0), page_num=0, block_id=1,
    )


def test_blank_paragraphs_do_not_reach_the_chapter_body():
    body = pk._prepare_chapter_body([_para(""), _para("real text"), _para("  ")])
    assert "real text" in body
    assert body.count("<p") == 1


def test_br_runs_collapse_to_one_separator():
    body = pk._prepare_chapter_body([_para("Line one<br/><br/><br/>Line two")])
    assert body.count("<br/>") == 1
    assert "Line one" in body and "Line two" in body


def test_an_all_empty_chapter_fails_loudly():
    with pytest.raises(ValueError, match="rendered empty"):
        pk._prepare_chapter_body([_para(""), _para("   ")])


# ---------------------------------------------------------------------------
# The structural check flags empties and forced breaks
# ---------------------------------------------------------------------------

CONTAINER_XML = (
    '<?xml version="1.0"?>'
    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)
OPF = (
    '<?xml version="1.0"?>'
    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
    'unique-identifier="id"><metadata/><manifest/><spine/></package>'
)


def _minimal_epub(path: Path, body_html: str) -> None:
    xhtml = (
        '<?xml version="1.0"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
        f"<body>{body_html}</body></html>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("content.opf", OPF)
        zf.writestr("chapter.xhtml", xhtml)


def _messages(path: Path) -> list[str]:
    return [e["message"] for e in pk.internal_structure_check(str(path))]


def test_structural_check_flags_empty_paragraph(tmp_path):
    epub = tmp_path / "ep.epub"
    _minimal_epub(epub, "<p>real</p><p></p>")
    assert "empty paragraph" in _messages(epub)


def test_structural_check_flags_empty_chapter_body(tmp_path):
    epub = tmp_path / "ep.epub"
    _minimal_epub(epub, "")
    assert "empty chapter body" in _messages(epub)


def test_structural_check_flags_forced_page_breaks(tmp_path):
    epub = tmp_path / "ep.epub"
    _minimal_epub(epub, '<p style="page-break-before: always">x</p>')
    assert "forced page break in reflowable EPUB" in _messages(epub)


def test_structural_check_flags_double_escaping(tmp_path):
    # built at runtime: the artifact itself must survive every editor
    artifact = chr(38) + "amp;"
    epub = tmp_path / "esc.epub"
    _minimal_epub(epub, f"<p>Tom {artifact}amp; Jerry</p>")
    joined = "; ".join(_messages(epub))
    assert "double-escaped entity" in joined


def test_structural_check_flags_unresolved_navigation_anchor(tmp_path):
    epub = tmp_path / "nav.epub"
    _minimal_epub(
        epub,
        '<p id="sec1">x</p><a href="chapter.xhtml#sec1">ok</a>'
        '<a href="chapter.xhtml#sec404">gone</a>',
    )
    joined = "; ".join(_messages(epub))
    assert joined.count("unresolved navigation anchor") == 1


def test_structural_check_passes_a_meaningful_body(tmp_path):
    epub = tmp_path / "ep.epub"
    _minimal_epub(epub, "<p>real prose</p>")
    msgs = _messages(epub)
    assert "empty paragraph" not in msgs
    assert "empty chapter body" not in msgs
    assert "forced page break in reflowable EPUB" not in msgs
    assert "double-escaped entity" not in msgs
    assert "unresolved navigation anchor" not in msgs
