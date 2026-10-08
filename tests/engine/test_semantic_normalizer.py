"""Deterministic semantic normalization (remediation Fix 4/5/6).

Linkify and listify are pinned against the plan's own edge-case lists:
trailing punctuation outside URLs, balanced parens, query entities,
isolated markers staying prose, non-1 ordered starts, sub-rank bullets
nesting when the sequence resumes, and page-spanning runs.
"""

from pdf2epub.engine.semantic_normalizer import (
    build_lists,
    linkify_urls,
    normalize_semantics,
)
from pdf2epub.engine.tier1_classifier import ElementType, StreamElement

E = chr(38) + "amp;"


def para(text, page=0):
    return StreamElement(
        element_type=ElementType.PARAGRAPH, tag="p", content=text,
        bbox=(54.0, 120.0, 314.0, 132.0), page_num=page, block_id=1,
    )


def blocks(stream):
    return [(e.element_type.name, e.tag, e.content) for e in stream]


# ---------------------------------------------------------------------------
# linkify (Fix 5)
# ---------------------------------------------------------------------------


def test_plain_url_becomes_one_anchor():
    (out,) = linkify_urls([para("Visit https://example.com today.")])
    assert out.content == 'Visit <a href="https://example.com">https://example.com</a> today.'


def test_trailing_sentence_punctuation_stays_outside_the_anchor():
    (out,) = linkify_urls([para("Docs live at https://docs.example.com/guide.")])
    assert out.content.endswith('">https://docs.example.com/guide</a>.')


def test_closing_paren_outside_but_balanced_parens_inside():
    (out,) = linkify_urls([para("See https://en.wikipedia.org/wiki/Foo_(disambiguation) here.")])
    assert "href=\"https://en.wikipedia.org/wiki/Foo_(disambiguation)\"" in out.content
    (out2,) = linkify_urls([para("Ref (https://example.com/x) helps.")])
    assert out2.content == 'Ref (<a href="https://example.com/x">https://example.com/x</a>) helps.'


def test_query_ampersand_entities_survive_single_escaped():
    url = "https://example.com/?q=1" + E + "x=2"
    (out,) = linkify_urls([para("See " + url + " now.")])
    assert out.content == (
        'See <a href="' + url + '">' + url + "</a> now."
    )


def test_strings_without_a_scheme_stay_plain_text():
    (out,) = linkify_urls([para("Visit example.com or ftp://x maybe.")])
    assert "<a " not in out.content


def test_existing_anchors_are_never_wrapped_twice():
    src = 'Read <a href="https://example.com">the docs</a> and https://example.com too.'
    (out,) = linkify_urls([para(src)])
    assert out.content.count("<a href=") == 2
    assert "the docs" in out.content


# ---------------------------------------------------------------------------
# listify (Fix 6)
# ---------------------------------------------------------------------------


def test_digit_run_becomes_an_ol():
    stream = [para("1. Alpha"), para("2. Beta"), para("3. Gamma")]
    out = build_lists(stream)
    assert len(out) == 1
    kind, tag, content = blocks(out)[0]
    assert (kind, tag) == ("BLOCK", "ol")
    assert "<li>Alpha</li><li>Beta</li><li>Gamma</li>" in content
    assert "start=" not in content


def test_ol_starting_past_one_keeps_its_start():
    stream = [para("5. Fifth"), para("6. Sixth")]
    out = build_lists(stream)[0]
    assert out.tag == "ol"
    assert out.attrs == ' start="5"'
    # the start attribute rides on the opening tag, never in the content
    assert out.render().startswith('<ol start="5"><li>Fifth</li>')


def test_glyph_bullets_become_a_ul():
    stream = [para("\u2022 First thing"), para("\u2022 Second thing")]
    (kind, tag, content) = blocks(build_lists(stream))[0]
    assert (kind, tag) == ("BLOCK", "ul")
    assert "<li>First thing</li>" in content


def test_an_isolated_marker_stays_a_paragraph():
    stream = [para("1. Lone item"), para("Plain prose follows.")]
    out = build_lists(stream)
    assert [e.element_type for e in out] == [ElementType.PARAGRAPH] * 2


def test_letter_bullets_cannot_open_a_list():
    # "a lot of text" must never become a bullet
    stream = [para("a lot of things happen"), para("a second sentence here")]
    out = build_lists(stream)
    assert all(e.element_type is ElementType.PARAGRAPH for e in out)


def test_eg_like_text_stays_prose():
    (out,) = build_lists([para("e.g. something illustrative")])
    assert out.element_type is ElementType.PARAGRAPH


def test_sub_rank_bullets_nest_when_the_sequence_resumes():
    stream = [
        para("7. Write a clean_review function that:"),
        para("o strips HTML tags first"),
        para("o lowercases everything"),
        para("8. Build the lemmatizer once"),
    ]
    out = build_lists(stream)
    assert len(out) == 1
    _, tag, content = blocks(out)[0]
    assert tag == "ol"
    assert "<li>Write a clean_review function that:<ul>" in content
    assert "<li>strips HTML tags first</li>" in content
    assert "<li>lowercases everything</li>" in content
    assert "</ul></li><li>Build the lemmatizer once</li>" in content


def test_runs_span_source_pages():
    stream = [para(f"{i}. Item {i}", page=0) for i in range(1, 4)]
    stream += [para(f"{i}. Item {i}", page=1) for i in range(4, 6)]
    out = build_lists(stream)
    assert len(out) == 1
    assert out[0].content.count("<li>") == 5


def test_a_decreasing_number_ends_the_run():
    stream = [para("1. One"), para("2. Two"), para("1. Restarted alone")]
    out = build_lists(stream)
    assert [e.element_type for e in out] == [
        ElementType.BLOCK, ElementType.PARAGRAPH,
    ]


def test_headings_break_runs_but_survive():
    from pdf2epub.engine.tier1_classifier import StreamElement as SE

    def heading(text):
        return SE(
            element_type=ElementType.HEADING, tag="h4", content=text,
            bbox=(54.0, 90.0, 314.0, 110.0), page_num=0, block_id=0, level=4,
        )

    stream = [para("1. One"), heading("Section"), para("2. Two")]
    out = build_lists(stream)
    assert [e.element_type for e in out] == [
        ElementType.PARAGRAPH, ElementType.HEADING, ElementType.PARAGRAPH,
    ]


# ---------------------------------------------------------------------------
# Composition (Fix 4: one boundary, structure before inline links)
# ---------------------------------------------------------------------------


def test_normalize_semantics_links_urls_inside_list_items():
    stream = [
        para("1. See https://example.com/a"),
        para("2. And https://example.com/b"),
    ]
    out = normalize_semantics(stream)
    assert len(out) == 1
    content = out[0].content
    assert "<li>See " in content
    assert '<a href="https://example.com/a">' in content
    assert '<a href="https://example.com/b">' in content


# ---------------------------------------------------------------------------
# End to end: the nested-lists fixture (Fix 17 regression class)
# ---------------------------------------------------------------------------


def test_nested_lists_fixture_end_to_end(fixture_pdfs, tmp_path):
    import zipfile

    from pdf2epub.engine import driver

    out = tmp_path / "lists.epub"
    result = driver.run_pipeline(
        fixture_pdfs["nested_lists"], str(out),
        llm_adapter=None, verbose=False, cache_dir=str(tmp_path / "cache"),
    )
    assert result["success"] is True
    build = result["build"]
    m = build.metrics
    assert m.lists == 2          # the ordered workflow + the glyph bullets
    assert m.list_items == 8     # 3 ordered + 3 nested subs + 2 glyph
    assert m.chapters == 1
    assert m.unresolved_nav_targets == 0
    with zipfile.ZipFile(out) as zf:
        body = "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml")
        )
    assert "<li>Prepare the data<ul><li>clean the columns</li>" in body
    assert "<li>join the frames</li></ul></li>" in body
    assert "</ul></li><li>Train the model" in body
    assert "<li>alpha option</li><li>beta option</li>" in body


def test_staggered_table_rebuilds_offline(fixture_pdfs, tmp_path):
    """Fix 10: a staggered table page becomes a semantic table offline.

    Staggered cells fall under the router's columnar-overlap threshold,
    so this page legitimately stays on Tier 1 -- where extract_tables
    rebuilds the proven grid. The geometry a grid cannot explain stays
    prose (aligned pairs, ragged rows), per the plan's rule.
    """
    import zipfile

    from pdf2epub.engine import driver

    out = tmp_path / "table.epub"
    result = driver.run_pipeline(
        fixture_pdfs["staggered_table"], str(out),
        llm_adapter=None, verbose=False, cache_dir=str(tmp_path / "cache"),
    )
    assert result["success"] is True
    build = result["build"]
    assert build.metrics.tables == 1
    assert build.a11y.has_tables is True
    with zipfile.ZipFile(out) as zf:
        body = "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml")
        )
    assert "<td>Widget frame assembly</td>" in body
    assert "<td>aluminium housing, 12 mm bore</td>" in body
    assert "<td>Bolt set with washers</td>" in body
    assert "<td>nylon quick-release pair</td>" in body
    # the surrounding prose survives outside the grid
    assert "Parts Catalog" in body
    assert "paying reader" in body


def test_digest_fallback_rebuilds_staggered_tables():
    """The same geometry on a digest-routed page: the offline fallback
    rebuilds the grid there too (Fix 10, digest seam)."""
    from pdf2epub.engine.tier2_llm_handler import Tier2Request, _digest_fallback

    def d(line_id, block, bbox, text, bold=False):
        return {
            "line_id": line_id, "block_id": block, "bbox": bbox,
            "size": 10.0, "bold": bold, "italic": False, "text": text,
        }

    digest = [
        d(1, 1, (54.0, 90.0, 200.0, 104.0), "Parts Listing"),
        d(2, 2, (54.0, 120.0, 160.0, 134.0), "Widget frame assembly"),
        d(3, 2, (240.0, 128.0, 380.0, 142.0), "aluminium housing, 12 mm bore"),
        d(4, 3, (54.0, 150.0, 160.0, 164.0), "Bolt set with washers"),
        d(5, 3, (240.0, 158.0, 380.0, 172.0), "steel thread, M4 by 16 mm"),
        d(6, 4, (54.0, 180.0, 160.0, 194.0), "Panel clip retainers"),
        d(7, 4, (240.0, 188.0, 380.0, 202.0), "nylon quick-release pair"),
    ]
    xhtml = _digest_fallback(
        Tier2Request(page_num=1, layout_digest=digest, page_width=420.0)
    )
    assert "<table>" in xhtml
    assert "<td>Widget frame assembly</td>" in xhtml
    assert "<td>nylon quick-release pair</td>" in xhtml
    assert "<h4>Parts Listing</h4>" in xhtml
