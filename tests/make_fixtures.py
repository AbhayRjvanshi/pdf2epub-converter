"""
Synthetic PDF fixtures for the conversion pipeline tests.

Text is written word by word with explicit justification so that every
non-final line of a paragraph ends exactly on the right margin. That is what
real typeset books look like, and it is what the block-relative wrap detector
in Module 1 keys off.
"""

from __future__ import annotations

from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

PAGE_W, PAGE_H = 420.0, 680.0
MARGIN_X = 54.0
COL_W = 260.0
BODY_SIZE = 10.0
LINE_H = 14.0
HEADER_TEXT = "A Test Publication"

Run = tuple[str, "str | None"]  # (text, fontname override)


# ---------------------------------------------------------------------------
# Low-level writers
# ---------------------------------------------------------------------------


def _runs(text: str, font: str | None = None) -> list[Run]:
    return [(w, font) for w in text.split()]


def put_line(
    page,
    x0: float,
    y: float,
    width: float,
    runs: list[Run],
    size: float = BODY_SIZE,
    font: str = "helv",
    justify: bool = True,
) -> None:
    widths = [
        fitz.get_text_length(w, fontname=(f or font), fontsize=size) for w, f in runs
    ]
    natural_space = fitz.get_text_length(" ", fontname=font, fontsize=size)
    gaps = max(len(runs) - 1, 1)
    if justify and len(runs) > 1:
        # Real typesetting stretches word spacing; it never compresses words
        # into each other. Compressed output would make the space glyphs
        # unrecoverable, which is not what a real book PDF looks like.
        # Stretch, never compress, and never beyond what a typesetter would
        # accept: past ~2.5x the extractor stops seeing one visual line.
        gap = min(max((width - sum(widths)) / gaps, natural_space), natural_space * 2.4)
    else:
        gap = natural_space
    x = x0
    for (word, wfont), w_len in zip(runs, widths):
        page.insert_text((x, y), word, fontname=(wfont or font), fontsize=size)
        x += w_len + gap


def put_paragraph(
    page,
    x0: float,
    y: float,
    width: float,
    lines: list[list[Run]],
    size: float = BODY_SIZE,
    font: str = "helv",
    line_h: float = LINE_H,
) -> float:
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        put_line(page, x0, y + i * line_h, width, line, size, font, justify=not last)
    return y + len(lines) * line_h


def greedy_wrap(text: str, width: float, size: float = BODY_SIZE, font: str = "helv"
                ) -> list[list[Run]]:
    """Wrap to a measure, leaving slack so justification stretches, not squeezes."""
    target = width * 0.94
    words = text.split()
    lines: list[list[str]] = []
    cur: list[str] = []
    for w in words:
        trial = cur + [w]
        if cur and fitz.get_text_length(
            " ".join(trial), fontname=font, fontsize=size
        ) > target:
            lines.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return [[(w, None) for w in line] for line in lines]


def put_heading(page, x0: float, y: float, text: str, size: float) -> float:
    page.insert_text((x0, y), text, fontname="hebo", fontsize=size)
    return y + size * 1.6


def put_furniture(page, page_number: int) -> None:
    page.insert_text((MARGIN_X, 40.0), HEADER_TEXT, fontname="helv", fontsize=8)
    page.insert_text((PAGE_W / 2, 655.0), str(page_number), fontname="helv", fontsize=8)


def make_square_png(size: int = 64) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, (40, 90, 160))
    pix.set_rect(fitz.IRect(12, 12, size - 12, size - 12), (240, 200, 60))
    return pix.tobytes("png")


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

FIVE_LINE_TEXT = (
    "Conversion pipelines fail in quiet ways and the worst of those failures "
    "are the ones that still produce a file which opens in a reader without "
    "any complaint at all, even though the prose inside it has been chopped "
    "into fragments that no human editor would ever have signed off on before "
    "sending the book out to a paying reader."
)

HYPHEN_LINES = [
    _runs("The parser must rejoin a word that was split by hy-"),
    _runs("phenation at the end of a line of text."),
]

INLINE_STYLE_LINES = [
    [
        *_runs("A single"),
        ("emphatic", "hebo"),
        *_runs("word and one"),
        ("slanted", "heit"),
        *_runs("word must"),
    ],
    _runs("survive the flattening of a line into markup."),
]

STRADDLE_TAIL_TEXT = (
    "A paragraph that begins at the foot of one page and finishes at the head "
    "of the next must be welded back together, otherwise the reader meets a "
    "hard break in the middle of a sentence that the author never wrote and a "
    "screen reader announces a new"
)
STRADDLE_HEAD_TEXT = (
    "paragraph that does not exist. Welding is decided by the punctuation and "
    "the capitalisation found at the seam."
)

CODE_LINES = [
    "def convert(path):",
    "    doc = open_pdf(path)",
    "    return build(doc)",
]

LEFT_COLUMN = [
    "Multi-column pages break the naive",
    "top-to-bottom reader because the",
    "stream order in the file does not",
    "match the visual reading order of",
    "the printed page at all.",
]
RIGHT_COLUMN = [
    "The router must notice the backward",
    "vertical jump combined with a large",
    "horizontal shift and send the page",
    "to the model with its coordinates",
    "attached rather than guessing.",
]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def build_clean_book(path: str | Path) -> str:
    doc = fitz.open()

    # -- page 1 ---------------------------------------------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 1)
    y = put_heading(p, MARGIN_X, 90.0, "Chapter One: Beginnings", 17.0)
    y = put_paragraph(p, MARGIN_X, y, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W)) + 10
    y = put_paragraph(p, MARGIN_X, y, COL_W, HYPHEN_LINES) + 10
    y = put_paragraph(p, MARGIN_X, y, COL_W, INLINE_STYLE_LINES) + 10
    put_paragraph(p, MARGIN_X, y, COL_W, greedy_wrap(STRADDLE_TAIL_TEXT, COL_W))

    # -- page 2 ---------------------------------------------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 2)
    y = put_paragraph(p, MARGIN_X, 90.0, COL_W, greedy_wrap(STRADDLE_HEAD_TEXT, COL_W)) + 12
    put_heading(p, MARGIN_X, y, "A Subsection Within One", 13.5)

    # -- page 3 ---------------------------------------------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 3)
    y = put_heading(p, MARGIN_X, 90.0, "Chapter Two: Methods", 17.0)
    y = put_paragraph(p, MARGIN_X, y, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W)) + 14
    for i, line in enumerate(CODE_LINES):
        indent = len(line) - len(line.lstrip())
        p.insert_text(
            (MARGIN_X + indent * 5.4, y + i * LINE_H),
            line.lstrip(),
            fontname="cour",
            fontsize=9.5,
        )
    y += len(CODE_LINES) * LINE_H + 14
    p.insert_text((MARGIN_X, y), "Listing 1. A three line function.", fontname="helv", fontsize=7.5)

    # -- page 4 : figure + caption ---------------------------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 4)
    y = put_paragraph(p, MARGIN_X, 90.0, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W)) + 16
    rect = fitz.Rect(MARGIN_X, y, MARGIN_X + 120, y + 120)
    p.insert_image(rect, stream=make_square_png())
    p.insert_text(
        (MARGIN_X, y + 138), "Figure 1. A rendered test square.", fontname="helv", fontsize=8
    )

    # -- page 5 : two columns --------------------------------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 5)
    for i, line in enumerate(LEFT_COLUMN):
        p.insert_text((MARGIN_X, 110.0 + i * LINE_H), line, fontname="helv", fontsize=BODY_SIZE)
    for i, line in enumerate(RIGHT_COLUMN):
        p.insert_text((235.0, 110.0 + i * LINE_H), line, fontname="helv", fontsize=BODY_SIZE)

    # -- page 6 : image only (scanned) ------------------------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_image(fitz.Rect(60, 80, 360, 380), stream=make_square_png(200))

    doc.set_metadata({"title": "Fixture Title", "author": "Fixture Author"})
    doc.save(str(path))
    doc.close()
    return str(path)


def build_single_column_page(path: str | Path) -> str:
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_paragraph(p, MARGIN_X, 90.0, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W))
    doc.save(str(path))
    doc.close()
    return str(path)


def build_two_column_page(path: str | Path) -> str:
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    for i, line in enumerate(LEFT_COLUMN):
        p.insert_text((MARGIN_X, 110.0 + i * LINE_H), line, fontname="helv", fontsize=BODY_SIZE)
    for i, line in enumerate(RIGHT_COLUMN):
        p.insert_text((235.0, 110.0 + i * LINE_H), line, fontname="helv", fontsize=BODY_SIZE)
    doc.save(str(path))
    doc.close()
    return str(path)


def build_interleaved_two_column_page(path: str | Path) -> str:
    """Emit matching left/right rows alternately to defeat backward-Y checks."""
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    for i, (left, right) in enumerate(zip(LEFT_COLUMN, RIGHT_COLUMN)):
        y = 110.0 + i * LINE_H
        p.insert_text((MARGIN_X, y), left, fontname="helv", fontsize=BODY_SIZE)
        p.insert_text((235.0, y), right, fontname="helv", fontsize=BODY_SIZE)
    doc.save(str(path))
    doc.close()
    return str(path)


def build_scanned_page(path: str | Path) -> str:
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_image(fitz.Rect(40, 40, 380, 380), stream=make_square_png(240))
    doc.save(str(path))
    doc.close()
    return str(path)


def build_no_heading_doc(path: str | Path) -> str:
    """Body text only: exercises the 'no headings at all' segmentation branch."""
    doc = fitz.open()
    for n in range(2):
        p = doc.new_page(width=PAGE_W, height=PAGE_H)
        put_paragraph(p, MARGIN_X, 90.0, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W))
    doc.save(str(path))
    doc.close()
    return str(path)


def build_structural_headings_doc(path: str | Path) -> str:
    """Body-size headings, lists, a table and a bold sentence (Phase K).

    The headings are printed at exactly body size with no bold, so the
    size-ratio ladder cannot find them; only the multi-signal structural
    pass can. The table deliberately mixes separated same-baseline cell
    pairs with a merged "Label Value" row, because real extractors emit
    both shapes and the merged row has perfectly clean local gaps.
    """
    doc = fitz.open()

    # -- page 1: headings, list shapes, bold sentence --------------------
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 1)
    y = 90.0
    for heading in ("Artificial Intelligence", "Dataset", "Project Title"):
        p.insert_text((MARGIN_X, y), heading, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H + 6
        y = put_paragraph(p, MARGIN_X, y, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W)) + 12
    for item in ("1. Count of Movies vs TV Shows", "2. Titles added per year", "11. Quit"):
        p.insert_text((MARGIN_X, y), item, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H
    y += 8
    for item in ("- Fill missing country values with Unknown.", "- Drop rows missing dates."):
        p.insert_text((MARGIN_X, y), item, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H
    p.insert_text(
        (MARGIN_X, y + 16), "This fragment matters deeply.",
        fontname="hebo", fontsize=BODY_SIZE,
    )

    # -- page 2: header row, split cells, one merged row, real heading ---
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 2)
    y = 100.0
    p.insert_text((MARGIN_X, y), "Field Value", fontname="helv", fontsize=BODY_SIZE)
    for left, right in (
        ("Dataset", "IMDB Dataset of 50K Movie Reviews"),
        ("Platform", "Kaggle"),
        ("Rows", "Fifty Thousand"),
    ):
        y += 20.0
        p.insert_text((MARGIN_X, y), left, fontname="helv", fontsize=BODY_SIZE)
        p.insert_text((200.0, y), right, fontname="helv", fontsize=BODY_SIZE)
    y += 14.0
    p.insert_text(
        (MARGIN_X, y), "License Free For Research",
        fontname="helv", fontsize=BODY_SIZE,
    )
    y += 40.0
    p.insert_text((MARGIN_X, y), "Objective", fontname="helv", fontsize=BODY_SIZE)
    put_paragraph(
        p, MARGIN_X, y + LINE_H + 4, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W)
    )

    doc.save(str(path))
    doc.close()
    return str(path)


def build_running_header_doc(path: str | Path) -> str:
    """Body-size running header on every page: promoted, then stripped.

    The header is title-shaped at body size, so the structural pass tags
    it h4 on every page; the cross-page furniture filter must then
    remove it. This pins the Phase K edge case: repeated page-top text
    must not survive as a swarm of headings.
    """
    doc = fitz.open()
    for _ in range(4):
        p = doc.new_page(width=PAGE_W, height=PAGE_H)
        p.insert_text((MARGIN_X, 40.0), "Running Header Text",
                      fontname="helv", fontsize=BODY_SIZE)
        put_paragraph(p, MARGIN_X, 90.0, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W))
    doc.save(str(path))
    doc.close()
    return str(path)


def build_all(out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return {
        "clean_book": build_clean_book(out / "clean_book.pdf"),
        "single_column": build_single_column_page(out / "single_column.pdf"),
        "two_column": build_two_column_page(out / "two_column.pdf"),
        "interleaved_two_column": build_interleaved_two_column_page(
            out / "interleaved_two_column.pdf"
        ),
        "scanned": build_scanned_page(out / "scanned.pdf"),
        "no_heading": build_no_heading_doc(out / "no_heading.pdf"),
        "structural_headings": build_structural_headings_doc(
            out / "structural_headings.pdf"
        ),
        "running_header": build_running_header_doc(out / "running_header.pdf"),
    }


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "fixtures"
    for name, p in build_all(target).items():
        print(f"{name:15} -> {p}")


def build_large_book(path: str | Path, pages: int = 120, logo_every: int = 10) -> str:
    """A long, well-behaved book for scale and throughput testing.

    Every ``logo_every`` pages carries the *same* logo bytes, which exercises
    content-hash image de-duplication: the EPUB must contain one copy, not
    ``pages // logo_every`` copies.
    """
    doc = fitz.open()
    body = greedy_wrap(FIVE_LINE_TEXT, COL_W)
    logo = make_square_png(48)
    for n in range(pages):
        p = doc.new_page(width=PAGE_W, height=PAGE_H)
        put_furniture(p, n + 1)
        y = 90.0
        if n % 25 == 0:
            y = put_heading(p, MARGIN_X, y, f"Chapter {n // 25 + 1}", 17.0)
        for _ in range(3):
            y = put_paragraph(p, MARGIN_X, y, COL_W, body) + 10
            if y > PAGE_H - 160:
                break
        if logo_every and n % logo_every == 0:
            p.insert_image(fitz.Rect(MARGIN_X, PAGE_H - 140, MARGIN_X + 48, PAGE_H - 92),
                           stream=logo)
            p.insert_text((MARGIN_X, PAGE_H - 80),
                          f"Figure {n // logo_every + 1}. House logo.",
                          fontname="helv", fontsize=8)
    doc.set_metadata({"title": "Large Fixture", "author": "Scale Test"})
    doc.save(str(path))
    doc.close()
    return str(path)
