"""Module 1: deterministic layout stream processor."""

import re

import pytest

import tier1_classifier as t1
from tier1_classifier import ElementType


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

    def line(y, block):
        return t1.ClassifiedLine(
            text="t", raw_text="t", tag="p", level=0, monospace=False, wrapped=True,
            bbox=(54.0, y, 314.0, y + 12), size=10.0, block_id=block,
            block_margin=314.0, first_word_width=20.0,
        )

    merged = t1.build_paragraphs([line(100, 1), line(114, 2)], profile)
    assert len(merged) == 2


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
