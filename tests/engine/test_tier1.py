"""Module 1: deterministic layout stream processor."""

import re
from pathlib import Path

import pytest

from pdf2epub.engine import tier1_classifier as t1
from pdf2epub.engine.tier1_classifier import ElementType


# ---------------------------------------------------------------------------
# Font profiling
# ---------------------------------------------------------------------------


def test_profile_finds_body_size_and_line_height(clean_profile):
    assert clean_profile.body_size == pytest.approx(10.0)
    assert clean_profile.line_height == pytest.approx(14.0, abs=0.5)
    assert "Helvetica" in clean_profile.main_font


def test_profile_is_character_weighted(monkeypatch):
    """Many short large-font spans must not outvote long body prose."""
    sizes = t1.Counter()
    for _ in range(40):
        sizes[24.0] += len("Caption")  # 40 short captions
    for _ in range(10):
        sizes[10.0] += len("A long paragraph of running body text " * 3)
    assert sizes.most_common(1)[0][0] == 10.0


def test_profile_raises_on_textless_document(fixture_pdfs):
    import pymupdf as fitz

    doc = fitz.open(fixture_pdfs["scanned"])
    with pytest.raises(ValueError):
        t1.DocumentFontProfile.build(doc)
    doc.close()


# ---------------------------------------------------------------------------
# Paragraph unwrapping - the regression that matters most
# ---------------------------------------------------------------------------


def test_long_paragraph_is_not_split_into_two_line_chunks(tier1_stream):
    paras = [e for e in tier1_stream if e.element_type is ElementType.PARAGRAPH]
    joined = [p.plain_text() for p in paras]
    body = next(p for p in joined if p.startswith("Conversion pipelines"))
    # The source paragraph wraps over seven lines; it must survive as one.
    assert body.endswith("paying reader.")
    assert "chopped into fragments" in body


def test_no_paragraph_is_a_bare_fragment(tier1_stream):
    """Guards against per-line or per-word paragraph explosion."""
    paras = [
        e for e in tier1_stream if e.element_type is ElementType.PARAGRAPH
    ]
    short = [p.plain_text() for p in paras if len(p.plain_text().split()) < 4]
    assert short == [], f"fragmented paragraphs: {short}"


def test_trailing_bbox_is_advanced_not_pinned():
    """Direct unit test of the state machine's gap reference."""
    profile = t1.DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")
    lines = [
        t1.ClassifiedLine(
            text=f"line{i}",
            raw_text=f"line{i}",
            tag="p",
            level=0,
            monospace=False,
            wrapped=True,
            bbox=(54.0, 100.0 + i * 14.0, 314.0, 112.0 + i * 14.0),
            size=10.0,
            block_id=1,
            block_margin=314.0,
            first_word_width=20.0,
        )
        for i in range(6)
    ]
    merged = t1.build_paragraphs(lines, profile)
    assert len(merged) == 1
    assert merged[0].raw_text.split() == [f"line{i}" for i in range(6)]


def test_paragraph_break_on_larger_gap():
    profile = t1.DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")

    def line(y, wrapped=True):
        return t1.ClassifiedLine(
            text="text", raw_text="text", tag="p", level=0, monospace=False,
            wrapped=wrapped, bbox=(54.0, y, 314.0, y + 12), size=10.0,
            block_id=1, block_margin=314.0, first_word_width=20.0,
        )

    merged = t1.build_paragraphs([line(100), line(114), line(160)], profile)
    assert len(merged) == 2


def test_different_blocks_do_not_merge():
    profile = t1.DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")

    def line(y, block, text="t"):
        return t1.ClassifiedLine(
            text=text, raw_text=text, tag="p", level=0, monospace=False,
            wrapped=True, bbox=(54.0, y, 314.0, y + 12), size=10.0,
            block_id=block, block_margin=314.0, first_word_width=20.0,
        )

    merged = t1.build_paragraphs([line(100, 1), line(114, 2)], profile)
    assert len(merged) == 1  # identical lowercase unterminated flow: a continuation


def test_cross_block_merge_needs_full_evidence():
    """Block identity alone no longer splits paragraphs (children's-book
    producers emit one text object per visual line), but the cross-block
    rule is over-determined: any missing piece of evidence -- column,
    alignment, list boundary, punctuation, case flow -- keeps the pair
    separate."""
    profile = t1.DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")

    def line(y, block, text, x0=54.0):
        return t1.ClassifiedLine(
            text=text, raw_text=text, tag="p", level=0, monospace=False,
            wrapped=True, bbox=(x0, y, x0 + 260.0, y + 12), size=10.0,
            block_id=block, block_margin=x0 + 260.0, first_word_width=20.0,
        )

    # capital start on the next line: no case-flow continuation
    assert len(t1.build_paragraphs(
        [line(100, 1, "First one."), line(114, 2, "Second one.")], profile
    )) == 2
    # terminal punctuation closes the previous sentence
    assert len(t1.build_paragraphs(
        [line(100, 1, "Sentence ends here."), line(114, 2, "and so on")], profile
    )) == 2
    # list markers are structural boundaries, never prose continuations
    assert len(t1.build_paragraphs(
        [line(100, 1, "then one item"), line(114, 2, "2. second item")], profile
    )) == 2
    # a shifted left edge is a new paragraph, a quote or another column
    assert len(t1.build_paragraphs(
        [line(100, 1, "and it runs on"), line(114, 2, "into more text", x0=120.0)],
        profile,
    )) == 2
    # disjoint x-ranges are different columns
    assert len(t1.build_paragraphs(
        [line(100, 1, "and it runs on"), line(114, 2, "into more text", x0=400.0)],
        profile,
    )) == 2
    # a paragraph break in the vertical flow
    assert len(t1.build_paragraphs(
        [line(100, 1, "and it runs on"), line(160, 2, "into more text")], profile
    )) == 2
    # with the full evidence stack, the pair welds across the boundary
    merged = t1.build_paragraphs(
        [line(100, 1, "The sentence continues onto"),
         line(114, 2, "the next line of the pair")], profile
    )
    assert len(merged) == 1
    assert merged[0].raw_text == (
        "The sentence continues onto the next line of the pair"
    )


# ---------------------------------------------------------------------------
# Hyphenation
# ---------------------------------------------------------------------------


def test_soft_hyphen_is_rejoined(tier1_stream):
    texts = " ".join(e.plain_text() for e in tier1_stream)
    assert "hyphenation" in texts
    assert "hy- phenation" not in texts
    assert "hy-phenation" not in texts


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("split by hy-", "phenation at the", True),
        ("the Anglo-", "Saxon kings", False),   # next fragment capitalised
        ("a self-", "contained unit", False),   # known compound prefix
        ("no hyphen here", "next line", False),
    ],
)
def test_soft_hyphen_discrimination(first, second, expected):
    assert t1._is_soft_hyphen(first, second) is expected


def test_hyphen_rejoin_preserves_inline_tags():
    out = t1.join_lines(
        "a <em>hy-</em>", "<em>phenated</em> word", "a hy-", "phenated word"
    )
    assert "hy</em><em>phenated" in out or "hyphenated" in out.replace("</em><em>", "")
    assert "hy-" not in out


# ---------------------------------------------------------------------------
# Inline styling
# ---------------------------------------------------------------------------


def test_inline_emphasis_survives_line_flattening(tier1_stream):
    html = " ".join(e.content for e in tier1_stream)
    assert "<strong>emphatic</strong>" in html
    assert "<em>slanted</em>" in html


def test_no_emphasis_tags_around_bare_spaces(tier1_stream):
    html = " ".join(e.content for e in tier1_stream)
    assert not re.search(r"<(strong|em|code)>\s*</\1>", html)


def test_heading_does_not_carry_redundant_strong(tier1_stream):
    heads = [e for e in tier1_stream if e.element_type is ElementType.HEADING]
    assert heads
    for h in heads:
        assert "<strong>" not in h.content


def test_coalesce_inline_tags():
    assert t1.coalesce_inline_tags("<em>a</em> <em>b</em>") == "<em>a b</em>"
    assert t1.coalesce_inline_tags("<em>a</em><strong>b</strong>") == (
        "<em>a</em><strong>b</strong>"
    )


# ---------------------------------------------------------------------------
# Space recovery from glyph geometry
# ---------------------------------------------------------------------------


def _char(c, x0, x1):
    return {"c": c, "bbox": (x0, 0.0, x1, 10.0), "origin": (x0, 8.0)}


def test_span_text_recovers_missing_word_spaces():
    span = {
        "size": 10.0,
        "chars": [
            _char("o", 0, 6), _char("n", 6, 12), _char("e", 12, 18),
            _char("t", 24, 30), _char("w", 30, 36), _char("o", 36, 42),
        ],
    }
    assert t1.span_text(span) == "one two"


def test_span_text_does_not_invent_spaces_in_tight_text():
    span = {
        "size": 10.0,
        "chars": [_char(c, i * 6, i * 6 + 6) for i, c in enumerate("word")],
    }
    assert t1.span_text(span) == "word"


def test_span_text_falls_back_to_plain_text():
    assert t1.span_text({"text": "already fine", "size": 10.0}) == "already fine"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def test_block_right_margin_ignores_a_single_overhang():
    # Four lines on the measure, one overhanging line, one short last line.
    assert t1.block_right_margin([314.0, 314.0, 314.0, 342.5, 138.0]) == 314.0


def test_merge_baseline_fragments_joins_same_line():
    frag = lambda x0, x1: {  # noqa: E731
        "bbox": (x0, 100.0, x1, 112.0),
        "spans": [{"size": 10.0, "text": "w", "bbox": (x0, 100.0, x1, 112.0)}],
    }
    merged = t1.merge_baseline_fragments([frag(54, 80), frag(90, 120), frag(130, 160)])
    assert len(merged) == 1
    assert merged[0]["bbox"][2] == 160


def test_merge_baseline_fragments_respects_column_gutter():
    frag = lambda x0, x1: {  # noqa: E731
        "bbox": (x0, 100.0, x1, 112.0),
        "spans": [{"size": 10.0, "text": "w", "bbox": (x0, 100.0, x1, 112.0)}],
    }
    merged = t1.merge_baseline_fragments([frag(54, 200), frag(280, 400)])
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# Code blocks and images
# ---------------------------------------------------------------------------


def test_code_block_is_single_pre_with_indentation(tier1_stream):
    blocks = [e for e in tier1_stream if e.element_type is ElementType.CODE_BLOCK]
    assert len(blocks) == 1
    lines = blocks[0].content.split("\n")
    assert lines[0].startswith("def convert")
    assert lines[1].startswith("    doc = open_pdf")
    assert blocks[0].render().startswith("<pre><code>")


def test_image_extracted_with_caption_alt_text(tier1_stream):
    images = [e for e in tier1_stream if e.element_type is ElementType.IMAGE]
    assert len(images) == 1
    img = images[0]
    assert img.image_data is not None
    assert img.image_data.image_bytes[:4] == b"\x89PNG"
    assert "Figure 1" in img.image_data.alt_text
    assert 'alt="Figure 1' in img.render()


def test_stream_elements_are_in_reading_order(tier1_stream):
    page4 = [e for e in tier1_stream if e.page_num == 3]
    kinds = [e.element_type for e in page4]
    assert ElementType.IMAGE in kinds
    ys = [e.bbox[1] for e in page4]
    assert ys == sorted(ys)


def test_render_escapes_alt_text():
    img = t1.ImageElement(
        ext="png", mime_type="image/png", bbox=(0, 0, 1, 1),
        page_num=0, block_id=0, alt_text='a "quoted" & odd caption', filename="x.png",
    )
    el = t1.StreamElement(ElementType.IMAGE, "figure", "", image_data=img)
    assert "&amp;" in el.render()
    assert '"quoted"' not in el.render()


def test_join_lines_keeps_a_url_hyphen():
    # A URL wrapped at its own hyphen: the hyphen is slug content,
    # stripping it rewrites the link to a nonexistent page.
    from pdf2epub.engine.tier1_classifier import ends_in_url_token, join_lines

    first = "See https://www.kaggle.com/datasets/shivamb/netflix-"
    joined = join_lines(first, "shows today.", first, "shows today.")
    assert joined == "See https://www.kaggle.com/datasets/shivamb/netflix-shows today."
    assert ends_in_url_token(first)
    assert not ends_in_url_token("an ordinary compound-")


def test_space_advance_measured_from_real_glyphs():
    from pdf2epub.engine.tier1_classifier import _space_advances

    def ch(c, x0, x1):
        return {"c": c, "bbox": (x0, 0.0, x1, 10.0)}

    span = {"chars": [ch("h", 0, 5), ch(" ", 5, 7.8), ch("i", 7.8, 12)]}
    assert _space_advances([span]) == [2.8]


def test_page_space_advance_median_and_zero_fallback():
    from pdf2epub.engine.tier1_classifier import _page_space_advance

    def span(spaces):
        return {"spans": [{"chars": [
            {"c": "a", "bbox": (0, 0, 5, 10)},
            *[{"c": " ", "bbox": (5 + i * 10, 0, 5 + i * 10 + spaces[i], 10)}
              for i in range(len(spaces))],
        ]}]}

    raw = {"blocks": [{"type": 0, "lines": [span([2.0, 3.0, 4.0])]}]}
    assert _page_space_advance(raw) == 3.0
    assert _page_space_advance({"blocks": []}) == 0.0


def test_code_collector_uses_measured_width_for_proportional_fonts():
    from pdf2epub.engine.tier1_classifier import (
        ClassifiedLine,
        DocumentFontProfile,
        _collect_code_blocks,
    )

    def pre_line(text, x0, y, char_width):
        return ClassifiedLine(
            text=text, raw_text=text, tag="pre", level=0, monospace=False,
            wrapped=False, bbox=(x0, y, x0 + 100.0, y + 14.0), size=10.0,
            block_id=1, char_width=char_width,
        )

    profile = DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")
    lines = [
        pre_line("def f():", 54.0, 100.0, 2.5),
        pre_line("return 1", 54.0 + 4 * 2.5, 114.0, 2.5),  # 4-space indent
        pre_line("x = 1", 54.0 + 8 * 2.5, 128.0, 2.5),    # 8-space indent
    ]
    (block,) = _collect_code_blocks(lines, 0, profile.line_height)
    assert block.content == "def f():\n    return 1\n        x = 1"


def test_code_collector_falls_back_to_estimate_without_measurement():
    from pdf2epub.engine.tier1_classifier import (
        ClassifiedLine,
        DocumentFontProfile,
        _collect_code_blocks,
    )

    def pre_line(text, x0, y):
        return ClassifiedLine(
            text=text, raw_text=text, tag="pre", level=0, monospace=True,
            wrapped=False, bbox=(x0, y, x0 + 100.0, y + 14.0), size=10.0,
            block_id=1,  # char_width=0.0 -> historical 0.6 x size estimate
        )

    profile = DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")
    lines = [pre_line("code()", 54.0, 100.0), pre_line("x", 54.0 + 6.0, 114.0)]
    (block,) = _collect_code_blocks(lines, 0, profile.line_height)
    assert block.content == "code()\n x"  # 6pt / 6pt = exactly one space


# ---------------------------------------------------------------------------
# Non-core image transcoding (corpus finding 3)
# ---------------------------------------------------------------------------

JPX_ASSET = (
    Path(__file__).resolve().parents[1] / "assets" / "jpx_sample.jp2"
)


def test_jpx_image_transcodes_to_core_png_at_extraction(fixture_pdfs):
    """A JPEG 2000 embed (ext jpx, genuine JP2 bytes) must never reach
    the EPUB as an image/png-labelled .jpx: it transcodes to real PNG at
    extraction, preserving pixel content and the alt-text contract."""
    import fitz

    doc = fitz.open(fixture_pdfs["jpx_image"])
    profile = t1.DocumentFontProfile.build(doc)
    elements = t1.build_page_stream(doc[0], profile, 0)
    doc.close()

    images = [
        e for e in elements
        if e.element_type is ElementType.IMAGE and e.image_data is not None
    ]
    assert len(images) == 1
    img = images[0].image_data
    assert img.ext == "png"
    assert img.mime_type == "image/png"
    assert img.image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert img.filename.endswith(".png")
    # visual content preserved: the packaged PNG keeps source dimensions
    out_pix = fitz.Pixmap(img.image_bytes)
    assert (out_pix.width, out_pix.height) == (80, 104)
    # alt text still harvested from the caption
    assert img.alt_text


def test_undecodable_image_is_dropped_with_diagnostic(monkeypatch, caplog):
    """A failed transcode must produce a clear diagnostic and must
    never silently relabel undecodable bytes as PNG."""
    import logging

    monkeypatch.setattr(t1, "_transcode_to_core", lambda data: None)
    page = _jpx_page_stub()
    with caplog.at_level(
        logging.WARNING, logger="pdf2epub.engine.tier1_classifier"
    ):
        dropped = t1.extract_images(page, 0, [], None)
    assert dropped == []  # skipped, not mislabeled
    assert "could not be transcoded" in caplog.text
    assert "jpx" in caplog.text


def _jpx_page_stub():
    """A minimal fitz.Page-like object carrying one jpx image block."""
    import types

    data = JPX_ASSET.read_bytes()

    class _Page:
        rect = types.SimpleNamespace(width=200.0, height=260.0)

        @staticmethod
        def get_text(kind):
            return {"dict": {"blocks": [{
                "type": 1, "number": 7,
                "bbox": (10.0, 32.0, 190.0, 240.0),
                "ext": "jpx", "image": data,
            }]}}.get(kind, {})

    return _Page()


def test_size_ladder_never_promotes_page_number_lines():
    """Corpus session 3 residual: a bold/large 'Page 43' promoted to h4
    via the font-size ladder, which runs before the structural signal
    pass. Page-number furniture is never a heading, whatever its size."""
    profile = t1.DocumentFontProfile(body_size=10.0, line_height=14.0, main_font="x")
    # large + bold would normally be h1/h2 territory
    tag, level = t1.classify_line_tag(16.0, True, profile)
    assert tag == "h1"
    tag, level = t1.classify_line_tag(16.0, True, profile, raw_text="Page 43")
    assert (tag, level) == ("p", 0)
    tag, level = t1.classify_line_tag(11.0, True, profile, raw_text="Page 2")
    assert (tag, level) == ("p", 0)


# ---------------------------------------------------------------------------
# Round 1 / WS2: document-norm boldness (flower-garden class)
# ---------------------------------------------------------------------------


def test_font_family_normalizes_weight_variants():
    """SegoePrint-Bold and SegoePrint are one family; base-14 aliases of
    different weights stay distinct families (bold evidence survives)."""
    assert t1.font_family("SegoePrint-Bold") == t1.font_family("SegoePrint")
    assert t1.font_family("SegoePrint-Bold") == "segoeprint"
    assert t1.font_family("helv") != t1.font_family("hebo")
    assert t1.font_family("") == ""
    assert t1.font_family("Helvetica-BoldItalic") == "helvetica"


def test_bold_body_narrative_discounts_boldness(fixture_pdfs):
    """An all-bold book: boldness is the document's voice, not signal.

    Profile must report it, narrative lines must stay <p> with no
    <strong>, the ladder-band line must not become h4, and the genuinely
    larger title must still climb the size ladder."""
    import fitz

    doc = fitz.open(fixture_pdfs["bold_body_narrative"])
    try:
        profile = t1.DocumentFontProfile.build(doc)
        assert profile.bold_char_share >= t1.BOLD_NOISE_SHARE
        assert profile.bold_is_structural is False
        lines = t1.classify_page(doc[0], profile)
        tags = {}
        for ln in lines:
            assert "<strong>" not in ln.text, ln.raw_text
            tags[ln.raw_text.strip()] = ln.tag
        for narrative in (
            "They could not wait to show their",
            "dad. They ran to the house and",
            "the garden gate and into the yard.",
            "hurry!",
            "gardens.",
            "A slightly larger bold line",
        ):
            assert tags[narrative] == "p", (narrative, tags[narrative])
        assert tags["Your Garden"] == "h1"
    finally:
        doc.close()


def test_mixed_typography_keeps_bold_evidence():
    """Bold stays structural evidence while it is rare: a mostly-regular
    document with a few bold words must not lose its heading signal."""
    import fitz

    doc = fitz.open()
    p = doc.new_page(width=420.0, height=680.0)
    p.insert_text((54.0, 100.0), "Regular body prose filling the page.",
                  fontname="helv", fontsize=10.0)
    for i in range(6):
        p.insert_text((54.0, 120.0 + i * 14.0), "More regular prose to balance the document.",
                      fontname="helv", fontsize=10.0)
    p.insert_text((54.0, 240.0), "A Bold Emphatic Word", fontname="hebo", fontsize=10.0)
    profile = t1.DocumentFontProfile.build(doc)
    doc.close()
    assert profile.bold_char_share < t1.BOLD_NOISE_SHARE
    assert profile.bold_is_structural is True
