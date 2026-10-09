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
        y += LINE_H + 6  # list items are separate lines, not a wrapped paragraph
    y += 8
    for item in ("- Fill missing country values with Unknown.", "- Drop rows missing dates."):
        p.insert_text((MARGIN_X, y), item, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H + 6
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


def build_nested_lists_doc(path: str | Path) -> str:
    """Ordered items with letter sub-bullets plus glyph bullets (Fix 6/17).

    The numbered workflow carries Wingdings-style 'o' sub-steps that
    nest when the sequence resumes, then a separate glyph-bullet list;
    every list shape the semantic normalizer must reconstruct.
    """
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 1)
    p.insert_text((MARGIN_X, 90.0), "Workflow Steps",
                  fontname="helv", fontsize=BODY_SIZE)
    y = 120.0
    for text in (
        "1. Prepare the data",
        "o clean the columns",
        "o join the frames",
        "2. Train the model",
        "o pick a metric",
        "3. Report the results",
    ):
        p.insert_text((MARGIN_X, y), text, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H + 6
    y += 10.0
    for text in ("- alpha option", "- beta option"):
        p.insert_text((MARGIN_X, y), text, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H + 6
    put_paragraph(p, MARGIN_X, y + 8, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W))
    doc.save(str(path))
    doc.close()
    return str(path)


def build_staggered_table_doc(path: str | Path) -> str:
    """A staggered-cell table page: digest-routed, rebuilt offline (Fix 10).

    The right-hand cells sit 8pt lower than their row partners -- the
    imperfect band overlap real extracted tables show -- which is the
    evidence that separates a table from a two-column article. The
    87pt gutter is past the router's columnar threshold, so the page
    takes the digest path; offline, the fallback must rebuild the grid
    instead of flattening it into prose.
    """
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_text((MARGIN_X, 90.0), "Parts Catalog",
                  fontname="helv", fontsize=BODY_SIZE)
    rows = [
        ("Widget frame assembly", "aluminium housing, 12 mm bore"),
        ("Bolt set with washers", "steel thread, M4 by 16 mm"),
        ("Panel clip retainers", "nylon quick-release pair"),
    ]
    y = 125.0
    for left, right in rows:
        p.insert_text((MARGIN_X, y), left, fontname="helv", fontsize=BODY_SIZE)
        p.insert_text((240.0, y + 8.0), right, fontname="helv", fontsize=BODY_SIZE)
        y += 30.0
    put_paragraph(p, MARGIN_X, y + 10, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W))
    doc.save(str(path))
    doc.close()
    return str(path)


def build_overlapping_prose_doc(path: str | Path) -> str:
    """Overlapping prose baselines: table evidence without a grid.

    28pt text on a 30pt advance makes consecutive line bands overlap
    by ~8.5pt (about 0.22 of the band height): enough vertical overlap
    to register as table-region evidence, never enough to cluster a
    grid row. This is the curved-decorative-font failure class that
    crashed ``extract_tables`` before the (markup, strays) contract was
    completed; ordinary prose, no genuine table data.
    """
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = 100.0
    for text in (
        "The twins are overjoyed",
        "A wonderful surprise",
        "Another has them confused",
        "Read on to find out why",
    ):
        p.insert_text((MARGIN_X, y), text, fontname="helv", fontsize=28.0)
        y += 30.0
    y += 20.0
    put_paragraph(
        p, MARGIN_X, y, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W, size=10.0)
    )
    doc.save(str(path))
    doc.close()
    return str(path)


def build_hyphen_url_doc(path: str | Path) -> str:
    """A URL wrapped at its own hyphen (soft-hyphen corruption class).

    The URL's real hyphen ('netflix-shows') sits exactly where a
    typographic soft hyphen would be. The pipeline must keep the
    hyphen and join the fragments directly; stripping it as a wrap
    artifact rewrites the link to a nonexistent page.
    """
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_text(
        (MARGIN_X, 90.0), "Dataset source and documentation",
        fontname="helv", fontsize=BODY_SIZE,
    )
    y = 120.0
    p.insert_text(
        (MARGIN_X, y),
        "See https://www.kaggle.com/datasets/shivamb/netflix-",
        fontname="helv", fontsize=BODY_SIZE,
    )
    p.insert_text(
        (MARGIN_X, y + LINE_H), "shows for the full catalogue.",
        fontname="helv", fontsize=BODY_SIZE,
    )
    doc.save(str(path))
    doc.close()
    return str(path)


def build_proportional_code_doc(path: str | Path) -> str:
    """Proportional-font code listings plus the false-positive zoo (Fix 9).

    Every listing is set in Helvetica -- the exact blind spot of the
    monospace-only classifier -- with indents positioned at whole
    multiples of the measured space advance, so the reconstructed space
    counts are unambiguous. The SQL run has no nearby label: it must
    qualify on the two-strong rule alone, and its title-cased SELECT
    line is the heading-promotion hazard this fixture pins. The
    negatives (prose mention, URL-only line, numbered list) prove the
    detector does not absorb ordinary content.
    """
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    space = fitz.get_text_length(" ", fontname="helv", fontsize=BODY_SIZE)
    base = MARGIN_X

    def put(text, y, level=0):
        p.insert_text(
            (base + level * 4 * space, y), text,
            fontname="helv", fontsize=BODY_SIZE,
        )

    y = 90.0
    put("Example implementation:", y)                    # label-boost source
    python_listing = [
        ("def convert(path):", 0),
        ("doc = open_pdf(path)", 1),
        ("if doc.page_count > 0:", 1),
        ('html = "<p>Tom & Jerry</p>"', 2),
        ("return build(doc, html)", 2),
        ("return None", 1),
    ]
    for text, level in python_listing:
        y += LINE_H
        put(text, y, level)

    y += 28.0
    put("The function returns a structured document.", y)  # run breaker
    y += 28.0
    put("result = client.get(url)", y)                     # second listing
    y += LINE_H
    put("print(result.status)", y)
    y += 28.0
    put("Call convert(path) to begin processing.", y)      # prose mention
    y += 28.0
    put("SELECT Name FROM Users", y)                       # no label nearby
    y += LINE_H
    put("WHERE Age > 30;", y)
    y += 28.0
    put("https://docs.example.com/convert", y)             # URL-only line
    y += 28.0
    put("1. Set retries = 5 in the config.", y)           # listify territory
    y += LINE_H + 6  # list items are separate lines, not a wrapped paragraph
    put("2. Import the library before use.", y)

    doc.save(str(path))
    doc.close()
    return str(path)


def build_special_chars_doc(path: str | Path) -> str:
    """Ampersands, angle brackets, quotes and a query-string URL.

    Escaping-ownership regression source (remediation Fix 12): every
    line passes through Tier-1 escape(), the OPF/nav title unescape, and
    ebooklib serialisation; each special character must appear exactly
    once in the packaged EPUB. No embedded metadata, so the first
    heading also exercises the title fallback with an ampersand in it.
    """
    doc = fitz.open()
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    put_furniture(p, 1)
    p.insert_text(
        (MARGIN_X, 90.0), "Rock & Roll Survey",
        fontname="helv", fontsize=BODY_SIZE,
    )
    lines = [
        'Tom & Jerry said 5 > 3 and 2 < 4, "quoted".',
        "See https://example.com/?q=1&x=2 for details.",
        "Docs live at https://docs.example.com/guide.",
        "Try the reference (see https://docs.example.com/tags) for help.",
        "Emphasis & nuance:",
    ]
    y = 120.0
    for text in lines:
        p.insert_text((MARGIN_X, y), text, fontname="helv", fontsize=BODY_SIZE)
        y += LINE_H
    put_paragraph(
        p, MARGIN_X, y + 10, COL_W, greedy_wrap(FIVE_LINE_TEXT, COL_W)
    )
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
        "nested_lists": build_nested_lists_doc(out / "nested_lists.pdf"),
        "staggered_table": build_staggered_table_doc(out / "staggered_table.pdf"),
        "overlapping_prose": build_overlapping_prose_doc(
            out / "overlapping_prose.pdf"
        ),
        "hyphen_url": build_hyphen_url_doc(out / "hyphen_url.pdf"),
        "proportional_code": build_proportional_code_doc(
            out / "proportional_code.pdf"
        ),
        "special_chars": build_special_chars_doc(out / "special_chars.pdf"),
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
