"""Deterministic multi-signal heading decision for same-size lines.

Font-size ratio is the primary heading signal and stays owned by the
callers' ratio ladders (Tier 1 and the offline digest fallback). This
module owns the secondary decision those ladders cannot make: a line at
body size can still be a *structural* heading when several independent
signals agree (stabilization plan, Phase K).

Conservative by construction -- every guard exists because a real
document class produces a false positive without it:

* list markers  -> menu items and bullet points are not headings;
* captions     -> "Figure 3 ..." lines are not headings;
* punctuation  -> a line that ends a sentence is a sentence;
* case shape   -> headings are Title Case, ALL CAPS or bold;
* table gaps   -> vertically overlapping neighbours mean a table;
* side-by-side -> text sharing your height in another column is
                  column or table geometry, never a heading;
* brevity      -> headings are short; wrapped text is not a heading.

Uncertainty always resolves to paragraph. Promotion is always to the
shallowest semantic claim (h4): a wrongly kept paragraph is cheap to
read past, a wrongly promoted line poisons the chapter split.
"""

from __future__ import annotations

import re
from html import escape

__all__ = [
    "structural_heading_level",
    "looks_like_table_row",
    "table_neighbourhood_gaps",
    "has_side_by_side_neighbour",
    "table_region",
    "in_table_region",
    "build_table_html",
]

# A leading isolated glyph (any bullet art), or an enumerator: "1.",
# "12)", "a.", "iv)". Headings do not start this way.
LIST_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"[^\w\s]"                 # bullet art: -, *, •, ▪, …
    r"|[0-9]{1,3}[.)]"
    r"|[a-z][.)]"
    r"|[IVXLCDM]{1,7}[.)]"
    r")\s+",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(
    r"^\s*(?:fig(?:ure)?|table|chart|image|plate|exhibit|listing|source)\b",
    re.IGNORECASE,
)
TRAILING_PUNCT_RE = re.compile(r"[.,;:!?…]\s*$")

MAX_WORDS = 8
MAX_CHARS = 72
TITLE_CASE_MIN_RATIO = 0.66
TABLE_OVERLAP_TOLERANCE = 2.0   # pt: gaps below -tolerance mean cell overlap
SIDE_BY_SIDE_X_GAP = 1.0        # x font size: clear horizontal separation
SIDE_BY_SIDE_Y_OVERLAP = 0.3    # of the shorter line's height

_SMALL_WORDS = frozenset(
    "a an the of in on for and or nor but to with by from at vs into onto "
    "over under is are was were be been being as per via not its it".split()
)


def _significant_words(text: str) -> list[str]:
    return [w for w in text.split() if any(c.isalpha() for c in w)]


def _is_title_like(text: str) -> bool:
    """Title Case / ALL CAPS shape, tolerating the usual small words."""
    words = _significant_words(text)
    if not words or not words[0][:1].isupper():
        return False
    if len(words) == 1:
        return True
    big = [w for w in words if w.lower() not in _SMALL_WORDS]
    if not big:
        return False
    upper = sum(1 for w in big if w[:1].isupper())
    return upper / len(big) >= TITLE_CASE_MIN_RATIO


def structural_heading_level(
    text: str,
    *,
    size: float,
    body_size: float,
    bold: bool = False,
) -> int | None:
    """Heading level for a same-size line, or None to keep it a paragraph.

    Callers run their own ratio ladders first; this decides only the
    residual band around body size (0.95 .. 1.15). Geometry guards
    (tables, columns) live with the callers, who own the page context.
    """
    ratio = size / body_size if body_size else 1.0
    if not (0.95 <= ratio < 1.15):
        return None
    plain = text.strip()
    if not plain or len(plain) > MAX_CHARS or len(plain.split()) > MAX_WORDS:
        return None
    if LIST_MARKER_RE.match(plain):
        return None
    if CAPTION_RE.match(plain):
        return None
    if TRAILING_PUNCT_RE.search(plain):
        return None
    if len(plain.split()) == 1 and any(c in plain for c in "()={}[]<>"):
        return None  # a lone code-shaped token (identifier(...), key=value)
    if not (bold or _is_title_like(plain)):
        return None
    return 4


def table_neighbourhood_gaps(bboxes: list[tuple], idx: int) -> list[float]:
    """Vertical gaps around entry ``idx``: own gap above, next two below.

    Table rows extracted as text often overlap vertically (negative gaps)
    because cells stack tighter than line spacing; the two-line look
    below catches a header row sitting just above the first overlap.
    """
    gaps: list[float] = []
    if idx > 0:
        gaps.append(bboxes[idx][1] - bboxes[idx - 1][3])
    if idx + 1 < len(bboxes):
        gaps.append(bboxes[idx + 1][1] - bboxes[idx][3])
    if idx + 2 < len(bboxes):
        gaps.append(bboxes[idx + 2][1] - bboxes[idx + 1][3])
    return gaps


def looks_like_table_row(gaps: list[float], *, overlap_limit: float | None = None) -> bool:
    """True when any adjacent vertical gap shows cell-overlap geometry.

    ``overlap_limit`` (typically ~3 line heights) rejects the huge
    negative "gaps" produced when the extractor's block order jumps from
    a page-bottom footer back up to the body: those are reading-order
    artefacts, not two text lines sharing a band.
    """
    for g in gaps:
        if g < -TABLE_OVERLAP_TOLERANCE and (
            overlap_limit is None or g >= -overlap_limit
        ):
            return True
    return False


def has_side_by_side_neighbour(
    bboxes: list[tuple], idx: int, *, size: float
) -> bool:
    """True when another line's box is x-disjoint but y-overlapping.

    A standalone heading owns its vertical band alone across the full
    measure. Text that shares its height in another column is column or
    table geometry -- however the extractor grouped the blocks -- and is
    never promoted (this is what guards the left cell of a table whose
    rows extract as tidy same-gap lines).
    """
    x0, y0, x1, y1 = bboxes[idx]
    height = y1 - y0
    if height <= 0:
        return False
    for j, (bx0, by0, bx1, by1) in enumerate(bboxes):
        if j == idx:
            continue
        x_disjoint = bx0 >= x1 + size * SIDE_BY_SIDE_X_GAP or x0 >= bx1 + size * SIDE_BY_SIDE_X_GAP
        if not x_disjoint:
            continue
        other_h = by1 - by0
        if other_h <= 0:
            continue
        overlap = min(y1, by1) - max(y0, by0)
        if overlap > min(height, other_h) * SIDE_BY_SIDE_Y_OVERLAP:
            return True
    return False


def table_region(
    bboxes: list[tuple],
    sizes: list[float],
    *,
    pad: float = 0.0,
    overlap_limit: float | None = None,
) -> tuple[float, float] | None:
    """Y-extent of table/column evidence (padded), or None.

    Lines that overlap vertically or sit side-by-side are table or
    column geometry. Their union spans a *region*: an extractor may
    merge a "Label Value" cell pair into one tidy line with clean
    neighbours, but it cannot move that line out of the region. Any
    promotion candidate whose band intersects the region is therefore
    rejected even when its own local gaps look innocent.

    ``pad`` (typically one line height) absorbs a header row printed a
    whisker above the first evidence line: "Field Value" has clean
    local gaps but is part of the table it names. ``overlap_limit``
    rejects reading-order jumps (see :func:`looks_like_table_row`).
    """
    top = bottom = None
    for i, bbox in enumerate(bboxes):
        if looks_like_table_row(
            table_neighbourhood_gaps(bboxes, i), overlap_limit=overlap_limit
        ) or (
            i < len(sizes) and has_side_by_side_neighbour(bboxes, i, size=sizes[i])
        ):
            top = bbox[1] if top is None else min(top, bbox[1])
            bottom = bbox[3] if bottom is None else max(bottom, bbox[3])
    if top is None:
        return None
    return top - pad, bottom + pad


def in_table_region(region: tuple[float, float] | None, bbox: tuple) -> bool:
    """True when ``bbox``'s band intersects a table region."""
    if region is None:
        return False
    return bbox[1] < region[1] and bbox[3] > region[0]


# ---------------------------------------------------------------------------
# Table reconstruction (remediation Fix 10)
# ---------------------------------------------------------------------------

_ROW_OVERLAP_FRACTION = 0.3   # of the shorter line: same visual row
_COLUMN_ALIGN_TOLERANCE = 0.6  # x font sizes: a cell continuation lines up


def _same_row(a: tuple, b: tuple) -> bool:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    height = min(a[3] - a[1], b[3] - b[1])
    return height > 0 and overlap > height * _ROW_OVERLAP_FRACTION


def build_table_html(
    lines: list[dict],
    *,
    size_hint: float = 10.0,
    already_escaped: bool = False,
) -> str | None:
    """Semantic table markup from a region's lines, or None.

    Rows are vertical band clusters; distinct x positions within a row
    are distinct cells. Two rules absorb the shapes real extractors
    produce without fabricating structure:

    * a single-line row that x-aligns with a cell of the grid row
      above continues that cell (a wrapped cell);
    * a single-line row that spans the full column extent is a merged
      header/footer bar and carries the honest colspan.

    Anything else that leaves the grid ragged returns None -- the
    caller then preserves the content as prose (the plan's "never
    fabricate cell relationships" rule).

    ``lines`` carry ``bbox`` and ``text`` plus an optional ``bold``
    flag; a fully bold first grid row becomes the table head. Text is
    raw and escaped here exactly once, unless the caller's pipeline
    already yields escaped XHTML (Tier 1's classified lines).

    Returns ``(markup, strays)``: leading single lines that precede
    any proven grid row (a caption, a heading above the table) are
    ejected to ``strays`` so the caller keeps them as prose instead of
    letting them poison the grid. ``markup`` is None when the grid
    itself cannot be proven.
    """
    if len(lines) < 2:
        return None, list(lines)

    ordered = sorted(lines, key=lambda d: (d["bbox"][1], d["bbox"][0]))
    rows: list[list[dict]] = []
    for ln in ordered:
        if rows and any(_same_row(prev["bbox"], ln["bbox"]) for prev in rows[-1]):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for row in rows:
        row.sort(key=lambda d: d["bbox"][0])

    # Table vs. columns: cleanly aligned side-by-side lines are exactly
    # what a two-column article looks like, and the plan forbids
    # guessing cell relationships the geometry does not prove. A
    # *staggered* row -- cells whose bands overlap imperfectly, the way
    # real extracted tables interleave -- is evidence no article
    # produces, because wrapped prose keeps its column baselines.
    multi_rows = [r for r in rows if len(r) > 1]
    if not multi_rows:
        # Candidate evidence did not produce a provable grid (curved or
        # overlapping prose baselines): every candidate line returns to
        # the prose fallback via the tuple contract -- never bare None,
        # which both seams unpack.
        return None, [c for r in rows for c in r]
    tol = size_hint * _COLUMN_ALIGN_TOLERANCE
    # Cells are x-disjoint by definition: a chain of same-x overlapping
    # lines is a stacked paragraph, never a row of cells. Without this
    # guard, curved decorative baselines fabricate single-row tables
    # out of prose.
    for row in multi_rows:
        if any(
            b["bbox"][0] < a["bbox"][2] - tol for a, b in zip(row, row[1:])
        ):
            return None, [c for r in rows for c in r]
    for row in multi_rows:
        for a, b in zip(row, row[1:]):
            overlap = min(a["bbox"][3], b["bbox"][3]) - max(a["bbox"][1], b["bbox"][1])
            height = min(a["bbox"][3] - a["bbox"][1], b["bbox"][3] - b["bbox"][1])
            if height > 0 and overlap < height * 0.5:
                break
        else:
            continue
        break
    else:
        return None, []  # every pair cleanly aligned: this could be prose columns

    resolved: list[list[dict]] = []
    strays: list[dict] = []
    grid_started = False
    for row in rows:
        if len(row) > 1:
            resolved.append(list(row))
            grid_started = True
            continue
        lone = row[0]
        if not grid_started:
            # nothing proven yet: a caption or heading above the grid
            # goes back to prose rather than poisoning the grid
            strays.append(lone)
            continue
        prev_multi = next(
            (r for r in reversed(resolved) if len(r) > 1), None
        )
        if prev_multi is not None:
            x0s = [c["bbox"][0] for c in prev_multi]
            x1s = [c["bbox"][2] for c in prev_multi]
            # a merged bar spans every column: test before column
            # continuation, because a spanning line also x-aligns with
            # the first column
            if (
                lone["bbox"][0] <= min(x0s) + tol
                and lone["bbox"][2] >= max(x1s) - tol
            ):
                resolved.append([{**lone, "_span": True}])
                continue
            column = next(
                (
                    i for i, cell in enumerate(prev_multi)
                    if abs(lone["bbox"][0] - cell["bbox"][0]) <= tol
                ),
                None,
            )
            if column is not None:
                # wrapped cell: continue the cell directly above
                cell = prev_multi[column]
                prev_multi[column] = {
                    **cell,
                    "text": cell["text"] + " " + lone["text"],
                    "bbox": (
                        cell["bbox"][0], cell["bbox"][1],
                        max(cell["bbox"][2], lone["bbox"][2]),
                        lone["bbox"][3],
                    ),
                }
                continue
        resolved.append([lone])  # unexplained: forces the ragged None

    grid = [r for r in resolved if len(r) > 1]
    if not grid:
        return None, strays + [c for r in resolved for c in r]
    width = len(grid[0])
    if any(len(r) != width for r in grid):
        return None, strays + [c for r in resolved for c in r]
    if any(
        len(row) < 2 and not row[0].get("_span") for row in resolved
    ):
        # an unexplained lone line is not a fabricated row; every
        # selected line returns to prose
        return None, strays + [c for r in resolved for c in r]

    def _text(cell: dict) -> str:
        inner = cell["text"].strip()
        return inner if already_escaped else escape(inner, quote=False)

    first_grid = resolved[0] if len(resolved[0]) > 1 else None
    header_row = first_grid if (
        first_grid is not None
        and len(grid) > 1
        and all(cell.get("bold") for cell in first_grid)
    ) else None

    parts: list[str] = []
    seen_body = False
    for row in resolved:
        if row is header_row:
            cells = "".join(f"<th>{_text(cell)}</th>" for cell in row)
            parts.append(f"<thead><tr>{cells}</tr></thead>")
            continue
        if row[0].get("_span"):
            parts.append(f'<tr><td colspan="{width}">{_text(row[0])}</td></tr>')
            seen_body = True
            continue
        cells = "".join(f"<td>{_text(cell)}</td>" for cell in row)
        parts.append(f"<tr>{cells}</tr>")
        seen_body = True
    if not parts:
        return None, strays + [c for r in resolved for c in r]
    body = "".join(parts)
    if seen_body and "<tbody>" not in body:
        body = f"<tbody>{body}</tbody>"
    return body, strays
