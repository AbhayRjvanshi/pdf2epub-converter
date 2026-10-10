"""Single-pass escaping ownership (remediation Fix 12).

Producers escape raw text exactly once; consumers that hand text to a
second XML serialiser (ebooklib: dc:title, chapter titles, nav labels)
unescape exactly once first. The matrix below is the plan's acceptance
list: &, <, >, quotes, URLs, table content, heading text.
"""

import zipfile

from pdf2epub.engine import driver
from pdf2epub.engine import tier2_llm_handler as t2
from pdf2epub.engine.tier2_llm_handler import sanitize_and_validate_xhtml

E = '&amp;'
DAM = '&amp;amp;'
LT = '&lt;'
GT = '&gt;'


# ---------------------------------------------------------------------------
# The sanitizer gate
# ---------------------------------------------------------------------------


def test_bare_ampersand_is_escaped_exactly_once():
    out = sanitize_and_validate_xhtml("<p>Tom & Jerry</p>")
    assert out == "<p>Tom " + E + " Jerry</p>"


def test_existing_entities_survive_untouched():
    src = "<p>Tom " + E + " Jerry <strong>x</strong></p>"
    out = sanitize_and_validate_xhtml(src)
    assert out == src


def test_named_entities_are_not_mangled_by_the_amp_guard():
    # Entity-shaped sequences must keep their "&": rewriting
    # "&mdash;" into "&amp;mdash;" displays literal garbage. lxml resolves
    # them to literal characters on the repair path.
    out = sanitize_and_validate_xhtml("<p>A &mdash; B &nbsp; C</p>")
    assert E + "mdash;" not in out
    assert E + "nbsp;" not in out
    assert "\u2014" in out or "&mdash;" in out


def test_numeric_character_references_survive_as_is():
    # Numeric references are valid XML: they pass the well-formed gate
    # untouched, no lxml repair needed.
    src = "<p>&#8212; &#x2014;</p>"
    out = sanitize_and_validate_xhtml(src)
    assert out == src


def test_malformed_pseudo_entities_are_still_fixed():
    # "AT&T" and "&foo bar" are bare ampersands in entity clothing.
    out = sanitize_and_validate_xhtml("<p>AT&T keeps &foo bar</p>")
    assert "AT" + E + "T" in out
    assert E + "foo" in out


def test_plain_text_fallback_never_double_escapes(monkeypatch):
    # The last resort receives text that still carries entities; it must
    # unescape back to raw text before its single re-escape.
    monkeypatch.setattr(t2, "is_well_formed", lambda html: (False, "broken"))
    monkeypatch.setattr(t2, "_lxml_repair", lambda html: None)
    out = sanitize_and_validate_xhtml(
        "<p>Tom " + E + " Jerry <b>bold</b> & more</p>"
    )
    assert "Tom " + E + " Jerry" in out
    assert DAM not in out
    assert "bold" in out
    assert E + " more" in out


def test_table_content_with_ampersands_round_trips():
    src = (
        "<table><tr><td>Tom " + E + " Jerry</td>"
        "<td>AT & T</td></tr></table>"
    )
    out = sanitize_and_validate_xhtml(src)
    assert "<td>Tom " + E + " Jerry</td>" in out
    assert "AT " + E + " T" in out
    assert DAM not in out


# ---------------------------------------------------------------------------
# The dc:title path: first-page heading -> OPF (escapes exactly once)
# ---------------------------------------------------------------------------


def test_first_page_title_candidate_unescapes_heading_text(fixture_pdfs):
    import fitz

    doc = fitz.open(fixture_pdfs["special_chars"])
    try:
        from pdf2epub.engine import tier1_classifier as t1

        profile = t1.DocumentFontProfile.build(doc)
        # raw "&", not "&amp;": ebooklib escapes when serialising the OPF
        assert (
            driver._first_page_title_candidate(doc, profile)
            == "Rock & Roll Survey"
        )
    finally:
        doc.close()


def test_special_characters_survive_to_the_epub_exactly_once(
    fixture_pdfs, tmp_path
):
    out = tmp_path / "special.epub"
    result = driver.run_pipeline(
        fixture_pdfs["special_chars"],
        str(out),
        llm_adapter=None,
        verbose=False,
        cache_dir=str(tmp_path / "cache"),
    )
    assert result["success"] is True
    with zipfile.ZipFile(out) as zf:
        body = "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml")
        )
        opf = "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".opf")
        )
    # & < > each escaped exactly once in the content
    assert "Tom " + E + " Jerry" in body
    assert "5 " + '&gt;' + " 3" in body
    assert "2 " + '&lt;' + " 4" in body
    assert DAM not in body
    # URL text intact, query ampersand single-escaped
    assert "https://example.com/?q=1" + E + "x=2" in body
    # linkify (Fix 5): every unambiguous URL is an anchor exactly once,
    # sentence punctuation outside, balanced parens kept
    assert 'href="https://docs.example.com/guide">https://docs.example.com/guide</a>.' in body
    assert 'href="https://docs.example.com/tags">https://docs.example.com/tags</a>)' in body
    assert body.count("href=") >= 3
    # heading text and dc:title both single-escaped at serialisation
    assert ">Rock " + E + " Roll Survey<" in body
    assert "<dc:title>Rock " + E + " Roll Survey</dc:title>" in opf


# ---------------------------------------------------------------------------
# The lxml decode -> stream seam (corpus finding, Fix 12 third hazard)
# ---------------------------------------------------------------------------


def test_tier2_stream_construction_reescapes_decoded_text():
    """lxml parses entities into DECODED text; the stream content
    contract is escaped inner XHTML. Without re-escaping, a code snippet
    like Popen(<your_command>, ...) leaks raw angle brackets that
    EPUBCheck then rejects as unknown elements."""
    src = (
        "<p>process = subprocess.Popen(" + LT + "your_command" + GT
        + ", stdout=1)</p>"
    )
    elements = driver.parse_xhtml_to_stream_elements(src, 0)
    assert len(elements) == 1
    content = elements[0].content
    assert "<your_command>" not in content
    assert "Popen(" + LT + "your_command" + GT in content


def test_tier2_unknown_tag_flattening_reescapes_text_content():
    src = "<custom>alpha " + LT + "tag" + GT + " beta</custom>"
    elements = driver.parse_xhtml_to_stream_elements(src, 0)
    assert len(elements) == 1
    content = elements[0].content
    assert "<tag>" not in content
    assert "alpha " + LT + "tag" + GT + " beta" == content


def test_decoded_code_snippet_round_trips_to_valid_xml():
    import xml.etree.ElementTree as ET

    src = (
        "<p>process = subprocess.Popen(" + LT + "your_command" + GT + ")</p>"
        "<p>if x " + LT + " 10: print('done')</p>"
    )
    elements = driver.parse_xhtml_to_stream_elements(src, 0)
    body = "\n".join(e.render() for e in elements)
    ET.fromstring(f"<root>{body}</root>")  # must parse: no raw tags leaked
