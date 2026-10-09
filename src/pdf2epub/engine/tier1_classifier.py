"""
Module 1: Tier 1 Deterministic Layout Stream Processor
======================================================

Translates PDF layout primitives (absolute coordinates, font bitmasks, isolated
character runs) into a continuous, document-wide stream of ``StreamElement``
objects.

This module does NOT write XHTML files. It emits a normalised element stream so
that downstream modules can strip running furniture, weld paragraphs across page
seams, and segment chapters at logical heading nodes.

Key mechanics
-------------
* Character-weighted font profiling (a title page cannot poison the baseline).
* Span-level inline styling (mid-sentence <strong>/<em>/<code> survives).
* Trailing-bbox paragraph unwrapping (no cumulative gap drift).
* Block-relative wrap detection (indented blockquotes are not falsely merged).
* Tag-aware hyphen rejoining, with a lexical guard against real compounds.
* Monospace run collection into <pre><code> with indentation preserved.
* Image block extraction with spatial alt-text harvesting.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from .code_signals import detect_code_lines
from .heading_signals import (
    build_table_html,
    in_table_region,
    structural_heading_level,
    table_region,
)
from enum import Enum, auto
from html import escape

try:  # PyMuPDF >= 1.24 prefers the `pymupdf` name; `fitz` is the legacy alias.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - fallback for older installs
    import fitz


# ---------------------------------------------------------------------------
# 0. Stream data model
# ---------------------------------------------------------------------------


class ElementType(Enum):
    HEADING = auto()
    PARAGRAPH = auto()
    CODE_BLOCK = auto()
    IMAGE = auto()
    SMALL_TEXT = auto()
    BLOCK = auto()  # table / blockquote / aside / list emitted by Tier 2


@dataclass
class ImageElement:
    """A figure in the stream.

    Image bytes are held either in memory (small jobs, unit tests) or spooled
    to a temporary file. A 500 page illustrated book can carry hundreds of
    megabytes of raster data; keeping all of it resident while the rest of the
    pipeline runs is the fastest way to have the process killed.
    """

    ext: str
    mime_type: str
    bbox: tuple[float, float, float, float]
    page_num: int
    block_id: int
    alt_text: str
    filename: str = ""
    image_bytes: bytes = b""
    source_path: str = ""

    def load_bytes(self) -> bytes:
        if self.image_bytes:
            return self.image_bytes
        if self.source_path:
            with open(self.source_path, "rb") as fh:
                return fh.read()
        return b""

    def byte_size(self) -> int:
        if self.image_bytes:
            return len(self.image_bytes)
        if self.source_path:
            try:
                return os.path.getsize(self.source_path)
            except OSError:
                return 0
        return 0


@dataclass
class StreamElement:
    """One semantic block in the document-wide stream.

    ``content`` holds the *inner* XHTML of the element, never the wrapper tag.
    Keeping the wrapper out of ``content`` is what makes cross-page welding a
    simple string join instead of a nested-tag repair job.
    """

    element_type: ElementType
    tag: str  # h1..h4, p, pre, figure
    content: str  # escaped inner XHTML fragment
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    page_num: int = 0
    block_id: int = 0
    level: int = 0  # heading depth, 0 for non-headings
    css_class: str = ""
    anchor_id: str = ""
    image_data: ImageElement | None = None
    attrs: str = ""  # extra opening-tag attributes, e.g. ol start="N"

    # -- rendering ---------------------------------------------------------
    def render(self) -> str:
        if self.element_type is ElementType.IMAGE and self.image_data is not None:
            src = f"../images/{self.image_data.filename}"
            alt = escape(self.image_data.alt_text, quote=True)
            return (
                f'<figure{self._id_attr()}>'
                f'<img src="{src}" alt="{alt}"/>'
                f"</figure>"
            )
        if self.element_type is ElementType.CODE_BLOCK:
            return f"<pre{self._id_attr()}><code>{self.content}</code></pre>"
        cls = f' class="{self.css_class}"' if self.css_class else ""
        if self.element_type is ElementType.BLOCK and self.tag.lower() == "table":
            return f'<div class="tbl"><table{self._id_attr()}{cls}>{self.content}</table></div>'
        return f"<{self.tag}{self._id_attr()}{cls}{self.attrs}>{self.content}</{self.tag}>"

    def _id_attr(self) -> str:
        return f' id="{self.anchor_id}"' if self.anchor_id else ""

    def plain_text(self) -> str:
        return strip_tags(self.content)


TAG_RE = re.compile(r"<[^>]+>")
ADJACENT_TAG_RE = re.compile(r"</(strong|em|code)>(\s*)<\1>")


def coalesce_inline_tags(html: str) -> str:
    """Collapse ``</strong> <strong>`` runs produced by span fragmentation."""
    previous = None
    while previous != html:
        previous = html
        html = ADJACENT_TAG_RE.sub(lambda m: m.group(2), html)
    return html


def strip_tags(html_text: str) -> str:
    return TAG_RE.sub("", html_text)


# ---------------------------------------------------------------------------
# 1. Global font & geometry profiling
# ---------------------------------------------------------------------------


@dataclass
class DocumentFontProfile:
    body_size: float
    line_height: float
    main_font: str
    size_histogram: Counter = field(default_factory=Counter)

    sampled_pages: int = 0

    @classmethod
    def build(
        cls, doc: "fitz.Document", max_sample_pages: int = 160
    ) -> "DocumentFontProfile":
        """Profile the document's typography.

        The baseline is a statistical mode, so it converges long before the
        whole book has been read. On a 600 page volume a full pass is a second
        wasted extraction of every page; an evenly spaced sample gives the same
        answer. Sampling is spread across the document so that front matter,
        body and back matter are all represented.
        """
        sizes: Counter = Counter()
        fonts: Counter = Counter()
        gaps: Counter = Counter()

        total = len(doc)
        if total <= max_sample_pages:
            indices = list(range(total))
        else:
            step = total / max_sample_pages
            indices = sorted({int(i * step) for i in range(max_sample_pages)})

        for page_index in indices:
            page = doc[page_index]
            raw = page.get_text("dict")
            for block in raw["blocks"]:
                if block.get("type") != 0:
                    continue
                prev_baseline = None
                for line in block["lines"]:
                    baseline = round(line["bbox"][3], 1)
                    if prev_baseline is not None:
                        gap = baseline - prev_baseline
                        if 0 < gap < 100:
                            # Bucket to 0.5pt: raw 0.1pt rounding shatters the
                            # mode across near-identical float values.
                            gaps[round(gap * 2) / 2] += 1
                    prev_baseline = baseline
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        sizes[round(span["size"], 1)] += len(text)
                        fonts[span["font"]] += len(text)

        if not sizes:
            raise ValueError("No extractable text layer found in document")

        body_size = sizes.most_common(1)[0][0]
        main_font = fonts.most_common(1)[0][0]
        line_height = gaps.most_common(1)[0][0] if gaps else round(body_size * 1.2, 1)
        return cls(
            body_size=body_size,
            line_height=line_height,
            main_font=main_font,
            size_histogram=sizes,
            sampled_pages=len(indices),
        )


# ---------------------------------------------------------------------------
# 2. Span bitmask decoding & inline serialisation
# ---------------------------------------------------------------------------

FLAG_SUPERSCRIPT = 1 << 0
FLAG_ITALIC = 1 << 1
FLAG_SERIF = 1 << 2
FLAG_MONOSPACE = 1 << 3
FLAG_BOLD = 1 << 4

BOLD_NAME_HINTS = ("bold", "black", "heavy", "semibold", "-bd", "demi")
ITALIC_NAME_HINTS = ("italic", "oblique", "-it")
MONO_NAME_HINTS = ("courier", "mono", "consolas", "menlo", "inconsolata")


def is_bold(span: dict) -> bool:
    if span.get("flags", 0) & FLAG_BOLD:
        return True
    name = span.get("font", "").lower()
    return any(h in name for h in BOLD_NAME_HINTS)


def is_italic(span: dict) -> bool:
    if span.get("flags", 0) & FLAG_ITALIC:
        return True
    name = span.get("font", "").lower()
    return any(h in name for h in ITALIC_NAME_HINTS)


def is_monospace(span: dict) -> bool:
    if span.get("flags", 0) & FLAG_MONOSPACE:
        return True
    name = span.get("font", "").lower()
    return any(h in name for h in MONO_NAME_HINTS)


SPACE_GAP_RATIO = 0.20  # a gap wider than 20% of the font size is a word break


def span_text(span: dict) -> str:
    """Span text with missing word spaces recovered from glyph positions.

    Many PDFs position words with absolute coordinates and never emit a space
    glyph. ``get_text("dict")`` then returns ``"onelongrunofwords"``. When
    per-character boxes are available (``rawdict``) the gaps between glyphs
    reveal the word breaks, so they are re-inserted here.
    """
    chars = span.get("chars")
    if not chars:
        return span.get("text", "")

    size = span.get("size", 10.0) or 10.0
    threshold = size * SPACE_GAP_RATIO
    out: list[str] = []
    prev_x1: float | None = None
    for ch in chars:
        glyph = ch.get("c", "")
        x0, x1 = ch["bbox"][0], ch["bbox"][2]
        if (
            prev_x1 is not None
            and glyph.strip()
            and out
            and out[-1].strip()
            and (x0 - prev_x1) > threshold
        ):
            out.append(" ")
        out.append(glyph)
        prev_x1 = x1
    return "".join(out)


def span_to_inline_xhtml(
    span: dict, *, text: str | None = None, suppress_bold: bool = False
) -> str:
    raw = span_text(span) if text is None else text
    escaped = escape(raw, quote=False)
    if not escaped:
        return ""
    if not raw.strip():
        return escaped  # pure spacing carries no emphasis
    if is_monospace(span):
        escaped = f"<code>{escaped}</code>"
    if is_bold(span) and not suppress_bold:
        escaped = f"<strong>{escaped}</strong>"
    if is_italic(span):
        escaped = f"<em>{escaped}</em>"
    return escaped


# ---------------------------------------------------------------------------
# 3. Line classification
# ---------------------------------------------------------------------------


@dataclass
class ClassifiedLine:
    text: str  # escaped XHTML with inline tags applied
    raw_text: str  # unescaped plain text (for lexical checks)
    tag: str  # h1..h4, p, small, pre
    level: int
    monospace: bool
    wrapped: bool  # ended near the parent block's right edge
    bbox: tuple[float, float, float, float]
    size: float
    block_id: int
    block_margin: float = 0.0
    first_word_width: float = 0.0
    bold: bool = False  # dominant span was bold (structural-heading evidence)
    char_width: float = 0.0  # measured space advance (0 -> collector fallback)


def classify_line_tag(size: float, bold: bool, profile: DocumentFontProfile) -> tuple[str, int]:
    ratio = size / profile.body_size if profile.body_size else 1.0
    if ratio >= 1.6:
        return "h1", 1
    if ratio >= 1.3:
        return "h2", 2
    if ratio >= 1.15:
        return ("h3", 3) if bold else ("h3", 3)
    if ratio >= 1.05 and bold:
        return "h4", 4
    if ratio <= 0.85:
        return "small", 0
    if bold and ratio >= 1.0 and ratio < 1.05:
        # Same-size all-bold standalone line: treat as h4 only if short.
        return "p", 0
    return "p", 0


def block_right_margin(right_edges: list[float]) -> float:
    """Typographic right margin of a block.

    Using ``max(right_edges)`` lets one overhanging line (a long URL, an
    unbreakable token, a last line that runs past the measure) poison the wrap
    test for every other line in the block. The 75th percentile is stable
    against a single outlier while still tracking the real measure.
    """
    if not right_edges:
        return 0.0
    ordered = sorted(right_edges)
    idx = int(0.75 * (len(ordered) - 1))
    return ordered[idx]


def _ends_near_block_margin(
    line_bbox: tuple, margin: float, tolerance_px: float = 15.0
) -> bool:
    return line_bbox[2] >= (margin - tolerance_px)


BASELINE_TOLERANCE = 1.5      # pt: same visual line
FRAGMENT_GAP_LIMIT = 4.0      # x font size: wider than this is a column gutter


def merge_baseline_fragments(block_lines: list[dict]) -> list[dict]:
    """Merge line fragments that share a baseline into one visual line.

    Widely tracked or heavily justified text makes the extractor emit each
    word as its own "line". Left alone, every such word becomes its own
    paragraph downstream. Fragments are merged only when the horizontal gap is
    small enough to be word spacing rather than a column gutter.
    """
    usable = [ln for ln in block_lines if ln.get("spans")]
    if len(usable) <= 1:
        return usable

    groups: list[list[dict]] = []
    for line in sorted(usable, key=lambda l: (round(l["bbox"][3], 1), l["bbox"][0])):
        if groups and abs(groups[-1][-1]["bbox"][3] - line["bbox"][3]) <= BASELINE_TOLERANCE:
            prev = groups[-1][-1]
            size = max(
                (sp.get("size", 10.0) for sp in prev["spans"]), default=10.0
            )
            if (line["bbox"][0] - prev["bbox"][2]) <= size * FRAGMENT_GAP_LIMIT:
                groups[-1].append(line)
                continue
        groups.append([line])

    merged: list[dict] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        spans: list[dict] = []
        for frag in group:
            spans.extend(frag["spans"])
        merged.append(
            {
                "bbox": (
                    min(f["bbox"][0] for f in group),
                    min(f["bbox"][1] for f in group),
                    max(f["bbox"][2] for f in group),
                    max(f["bbox"][3] for f in group),
                ),
                "spans": spans,
            }
        )
    return merged


def _space_advances(spans: list[dict]) -> list[float]:
    """Advance widths of real space glyphs in these spans, when present.

    Many PDFs position words without space glyphs (that is why
    :func:`span_text` recovers them from geometry); where glyphs exist,
    their boxes carry the true space advance of this exact font and
    size -- the quantity indentation reconstruction actually needs.
    """
    out: list[float] = []
    for span in spans:
        for ch in span.get("chars") or ():
            if ch.get("c") == " ":
                width = ch["bbox"][2] - ch["bbox"][0]
                if width > 0:
                    out.append(width)
    return out


def _page_space_advance(raw: dict) -> float:
    """Median observed space advance across the whole page, or 0.0.

    Page-level observation is the fallback for lines whose own text
    carries no space glyph (an indented ``x=5`` still needs a divisor
    from its neighbours). 0.0 means "unmeasured": the code collector
    then falls back to its historical 0.6 x font-size estimate.
    """
    advances: list[float] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                advances.extend(_space_advances([span]))
    if not advances:
        return 0.0
    ordered = sorted(advances)
    return ordered[len(ordered) // 2]


def classify_page(page: "fitz.Page", profile: DocumentFontProfile) -> list[ClassifiedLine]:
    """Flatten a page into classified lines, preserving block identity.

    Uses ``rawdict`` so that word spaces lost by the producing application can
    be recovered from glyph geometry.
    """
    out: list[ClassifiedLine] = []
    raw = page.get_text("rawdict")
    page_space = _page_space_advance(raw)

    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        block_id = block.get("number", 0)
        block_lines = merge_baseline_fragments(block["lines"])
        margin = block_right_margin([line["bbox"][2] for line in block_lines])

        for line in block_lines:
            spans = [s for s in line["spans"] if s.get("chars") or s.get("text")]
            if not spans:
                continue

            texts = [span_text(s) for s in spans]
            plain = _join_span_texts(spans, texts)
            if not plain.strip():
                continue

            all_mono = all(is_monospace(s) for s in spans)
            dominant = max(
                zip(spans, texts), key=lambda pair: len(pair[1].strip())
            )[0]
            tag, level = classify_line_tag(
                dominant["size"], is_bold(dominant), profile
            )
            if all_mono:
                tag, level = "pre", 0

            if all_mono:
                line_html = escape(plain.rstrip("\n"), quote=False)
            else:
                # A fully bold heading does not need <strong> inside it.
                suppress = tag.startswith("h") and all(is_bold(s) for s in spans)
                pieces = []
                for i, (sp, txt) in enumerate(zip(spans, texts)):
                    if i and _needs_gap(spans[i - 1], sp, texts[i - 1], txt):
                        pieces.append(" ")
                    pieces.append(
                        span_to_inline_xhtml(sp, text=txt, suppress_bold=suppress)
                    )
                line_html = coalesce_inline_tags("".join(pieces))

            line_bbox = tuple(line["bbox"])

            # Indentation divisor: this line's own space glyphs when it
            # has any, else the page's observed advance, else 0.0 (the
            # collector's historical 0.6 x size estimate applies).
            own_spaces = _space_advances(spans)
            own_spaces.sort()
            char_width = (
                own_spaces[len(own_spaces) // 2]
                if own_spaces
                else page_space
            )
            out.append(
                ClassifiedLine(
                    text=line_html if all_mono else line_html.strip(),
                    raw_text=plain,
                    tag=tag,
                    level=level,
                    monospace=all_mono,
                    wrapped=_ends_near_block_margin(line_bbox, margin),
                    bbox=line_bbox,
                    size=dominant["size"],
                    block_id=block_id,
                    block_margin=margin,
                    first_word_width=first_word_width(spans, texts),
                    bold=is_bold(dominant),
                    char_width=char_width,
                )
            )
    # Fix 9: proportional-font code runs become pre BEFORE heading
    # promotion, so title-cased code can never be promoted.
    out = detect_code_lines(out, profile)
    return promote_structural_headings(out, profile)


def promote_structural_headings(
    lines: list[ClassifiedLine], profile: DocumentFontProfile
) -> list[ClassifiedLine]:
    """Second-pass promotion of same-size structural headings (Phase K).

    The size ladder in :func:`classify_line_tag` answers "is this line
    bigger than body text?". This pass answers the complementary
    question for the residual paragraphs: "does this line *act* like a
    heading?" -- short, alone in its block, title-shaped, not a list
    item, caption, sentence, table row or column neighbour. Promotion is
    always to h4, the shallowest semantic heading claim; anything less
    certain stays a paragraph. Running headers that slip through are
    still removed downstream by the tag-agnostic furniture filter.
    """
    if not lines:
        return lines
    block_counts: dict[int, int] = {}
    for ln in lines:
        block_counts[ln.block_id] = block_counts.get(ln.block_id, 0) + 1
    bboxes = [ln.bbox for ln in lines]
    line_height = profile.line_height or (profile.body_size * 1.2)
    region = table_region(
        bboxes,
        [ln.size for ln in lines],
        pad=line_height,
        overlap_limit=3.0 * line_height,
    )
    for ln in lines:
        if ln.tag != "p" or ln.monospace:
            continue
        if block_counts.get(ln.block_id, 0) != 1:
            continue  # a heading does not share its block with wrapped text
        if in_table_region(region, ln.bbox):
            continue  # however the extractor shaped it, it is table/column text
        level = structural_heading_level(
            ln.raw_text, size=ln.size, body_size=profile.body_size, bold=ln.bold
        )
        if level is not None:
            ln.tag, ln.level = f"h{level}", level
    return lines


def first_word_width(spans: list[dict], texts: list[str]) -> float:
    """Width of the line's leading word, from glyph boxes where available."""
    for span, text in zip(spans, texts):
        chars = span.get("chars")
        if chars:
            x0 = None
            x1 = None
            for ch in chars:
                glyph = ch.get("c", "")
                if glyph.isspace():
                    if x0 is not None:
                        return max(0.0, x1 - x0)
                    continue
                if x0 is None:
                    x0 = ch["bbox"][0]
                x1 = ch["bbox"][2]
            if x0 is not None and x1 is not None:
                return max(0.0, x1 - x0)
        stripped = text.strip()
        if stripped:
            word = stripped.split()[0]
            return len(word) * span.get("size", 10.0) * 0.5
    return 0.0


def _needs_gap(prev_span: dict, span: dict, prev_text: str, text: str) -> bool:
    """Insert a space between two spans separated by horizontal whitespace."""
    if not prev_text or not text:
        return False
    if prev_text.endswith(" ") or text.startswith(" "):
        return False
    gap = span["bbox"][0] - prev_span["bbox"][2]
    size = max(span.get("size", 10.0), 1.0)
    return gap > size * SPACE_GAP_RATIO


def _join_span_texts(spans: list[dict], texts: list[str]) -> str:
    parts: list[str] = []
    for i, txt in enumerate(texts):
        if i and _needs_gap(spans[i - 1], spans[i], texts[i - 1], txt):
            parts.append(" ")
        parts.append(txt)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 4. Line rejoining (trailing-bbox state machine)
# ---------------------------------------------------------------------------

HYPHEN_BREAK_RE = re.compile(r"(\w)-((?:</\w+>)*)\s*$")

# Words that legitimately carry a hyphen; joining them would corrupt the text.
# Kept deliberately small: the dominant signal is that the *next* fragment
# starts with a capital letter or a digit, which almost never happens for a
# genuine soft hyphen.
KNOWN_COMPOUND_PREFIXES = (
    "self", "non", "anti", "pre", "post", "co", "re", "ex", "multi", "semi",
    "sub", "inter", "intra", "over", "under", "well", "half", "quasi", "pseudo",
)


def _is_soft_hyphen(first_plain: str, second_plain: str) -> bool:
    """Decide whether a trailing hyphen is a line-wrap artefact."""
    m = re.search(r"([A-Za-z]+)-$", first_plain.rstrip())
    if not m:
        return False
    head = m.group(1).lower()
    nxt = second_plain.lstrip()
    if not nxt:
        return False
    if not nxt[0].islower():
        # "Anglo-" + "Saxon" -> a real compound, keep the hyphen.
        return False
    if head in KNOWN_COMPOUND_PREFIXES:
        return False
    return True


URL_TOKEN_RE = re.compile(r"(?:https?://|www\.)\S*$")


def ends_in_url_token(plain: str) -> bool:
    """The last whitespace-delimited token is an in-progress URL.

    A hyphen at the end of a URL token is content -- slugs contain
    hyphens -- never a typographic soft hyphen: keep it and join the
    fragments directly, or the link is silently rewritten to a
    nonexistent page ('netflix-shows' becoming 'netflixshows').
    """
    return bool(URL_TOKEN_RE.search(plain.rstrip()))


def join_lines(first_html: str, second_html: str, first_plain: str, second_plain: str) -> str:
    first_html = first_html.rstrip()
    if HYPHEN_BREAK_RE.search(first_html) and ends_in_url_token(first_plain):
        # A URL wrapped at its own hyphen: the hyphen is content.
        return first_html + second_html.lstrip()
    if HYPHEN_BREAK_RE.search(first_html) and _is_soft_hyphen(first_plain, second_plain):
        match = HYPHEN_BREAK_RE.search(first_html)
        assert match is not None
        word_char, trailing_tags = match.group(1), match.group(2)
        first_html = HYPHEN_BREAK_RE.sub(
            lambda _m: word_char + trailing_tags, first_html
        )
        return first_html + second_html.lstrip()
    return first_html + " " + second_html.lstrip()


def build_paragraphs(
    lines: list[ClassifiedLine], profile: DocumentFontProfile
) -> list[ClassifiedLine]:
    """Merge wrapped lines into paragraph / heading primitives.

    Tracks ``buffer_last_bbox`` rather than the paragraph origin: comparing
    every new line against the origin makes the gap grow by one line height per
    row, which silently truncates every paragraph after its second line.
    """
    merged: list[ClassifiedLine] = []
    buffer: ClassifiedLine | None = None
    buffer_last_bbox: tuple | None = None
    buffer_plain: str = ""

    def flush() -> None:
        nonlocal buffer, buffer_last_bbox, buffer_plain
        if buffer is not None:
            merged.append(buffer)
        buffer = None
        buffer_last_bbox = None
        buffer_plain = ""

    for line in lines:
        if line.tag == "pre":
            flush()
            merged.append(line)
            continue

        if buffer is None:
            buffer, buffer_last_bbox, buffer_plain = line, line.bbox, line.raw_text
            continue

        assert buffer_last_bbox is not None
        vertical_gap = line.bbox[1] - buffer_last_bbox[1]
        lh = profile.line_height or (profile.body_size * 1.2)
        same_flow = abs(vertical_gap - lh) < (lh * 0.35)
        same_block = line.block_id == buffer.block_id
        same_tag = line.tag == buffer.tag
        size_match = abs(line.size - buffer.size) < 0.6

        space_est = max(buffer.size * 0.28, 1.0)
        next_word_would_not_fit = (
            buffer.block_margin > 0
            and (buffer.block_margin - buffer.bbox[2])
            < (line.first_word_width + space_est)
        )
        buffer_wrapped = buffer.wrapped or next_word_would_not_fit

        if same_flow and same_block and same_tag and size_match and buffer_wrapped:
            buffer = ClassifiedLine(
                text=join_lines(buffer.text, line.text, buffer_plain, line.raw_text),
                raw_text=(buffer_plain.rstrip() + " " + line.raw_text.lstrip()),
                tag=buffer.tag,
                level=buffer.level,
                monospace=False,
                wrapped=line.wrapped,
                block_margin=line.block_margin,
                first_word_width=buffer.first_word_width,
                bbox=(buffer.bbox[0], buffer.bbox[1], line.bbox[2], line.bbox[3]),
                size=buffer.size,
                block_id=buffer.block_id,
                bold=buffer.bold,
                char_width=buffer.char_width,
            )
            buffer_plain = buffer.raw_text
            buffer_last_bbox = line.bbox  # critical: advance the trailing edge
        else:
            flush()
            buffer, buffer_last_bbox, buffer_plain = line, line.bbox, line.raw_text

    flush()
    return merged


# ---------------------------------------------------------------------------
# 5. Image extraction
# ---------------------------------------------------------------------------

CAPTION_RE = re.compile(r"^\s*(fig(ure)?|table|plate|chart|image)\b", re.IGNORECASE)

MIME_BY_EXT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "webp": "image/webp",
}


def _harvest_alt_text(
    image_bbox: tuple, text_lines: list[ClassifiedLine], page_num: int, block_id: int
) -> str:
    """Prefer a caption sitting directly under the figure; otherwise stub it."""
    best: tuple[float, str] | None = None
    for line in text_lines:
        below_gap = line.bbox[1] - image_bbox[3]
        horizontally_overlapping = not (
            line.bbox[2] < image_bbox[0] - 20 or line.bbox[0] > image_bbox[2] + 20
        )
        if 0 <= below_gap <= 60 and horizontally_overlapping:
            txt = line.raw_text.strip()
            if not txt:
                continue
            score = below_gap - (100 if CAPTION_RE.match(txt) else 0)
            if best is None or score < best[0]:
                best = (score, txt)
    if best is not None:
        return best[1][:300]
    return f"Figure on page {page_num + 1}, block {block_id}"


def extract_images(
    page: "fitz.Page",
    page_index: int,
    text_lines: list[ClassifiedLine],
    spool_dir: str | None = None,
) -> list[StreamElement]:
    """Emit figure nodes, spooling raster data to disk when asked.

    Filenames are derived from a content hash, so a logo repeated on every
    page is written once and packaged once instead of 500 times.
    """
    elements: list[StreamElement] = []
    raw = page.get_text("dict")
    for block in raw["blocks"]:
        if block.get("type") != 1:
            continue
        data = block.get("image")
        if not data:
            continue
        ext = (block.get("ext") or "png").lower()
        block_id = block.get("number", 0)
        bbox = tuple(block["bbox"])
        alt = _harvest_alt_text(bbox, text_lines, page_index, block_id)
        digest = hashlib.sha1(data).hexdigest()[:16]
        filename = f"img_{digest}.{ext}"

        img = ImageElement(
            ext=ext,
            mime_type=MIME_BY_EXT.get(ext, "image/png"),
            bbox=bbox,
            page_num=page_index,
            block_id=block_id,
            alt_text=alt,
            filename=filename,
        )
        if spool_dir:
            path = os.path.join(spool_dir, filename)
            if not os.path.exists(path):  # content hash: identical bytes, one write
                with open(path, "wb") as fh:
                    fh.write(data)
            img.source_path = path
        else:
            img.image_bytes = data

        elements.append(
            StreamElement(
                element_type=ElementType.IMAGE,
                tag="figure",
                content="",
                bbox=bbox,
                page_num=page_index,
                block_id=block_id,
                image_data=img,
            )
        )
    return elements


# ---------------------------------------------------------------------------
# 6. Page -> stream
# ---------------------------------------------------------------------------


def _collect_code_blocks(
    units: list[ClassifiedLine], page_index: int, line_height: float
) -> list[StreamElement]:
    """Fold consecutive monospace lines into one <pre>, indentation intact.

    The indentation divisor is the line's measured space advance when
    space glyphs were observed (exact for any font, including
    proportional code from Fix 9 detection); otherwise the historical
    0.6 x font-size estimate applies -- which is exact for the
    monospace fonts this path was built for.
    """
    out: list[StreamElement] = []
    buf: list[ClassifiedLine] = []

    def flush_code() -> None:
        if not buf:
            return
        min_x = min(l.bbox[0] for l in buf)
        rendered = []
        for l in buf:
            char_w = max(l.char_width or (l.size * 0.6), 1.0)
            indent = max(0, int(round((l.bbox[0] - min_x) / char_w)))
            rendered.append(" " * indent + l.text.strip())
        out.append(
            StreamElement(
                element_type=ElementType.CODE_BLOCK,
                tag="pre",
                content="\n".join(rendered),
                bbox=(
                    min(l.bbox[0] for l in buf),
                    min(l.bbox[1] for l in buf),
                    max(l.bbox[2] for l in buf),
                    max(l.bbox[3] for l in buf),
                ),
                page_num=page_index,
                block_id=buf[0].block_id,
            )
        )
        buf.clear()

    for unit in units:
        if unit.tag == "pre":
            if buf:
                # Listings are routinely split into separate blocks by their
                # own indentation. Keep them together while the lines stay
                # vertically contiguous.
                gap = unit.bbox[1] - buf[-1].bbox[1]
                contiguous = 0 < gap < (line_height * 2.0)
                if not contiguous:
                    flush_code()
            buf.append(unit)
            continue
        flush_code()
        if unit.tag == "small":
            out.append(
                StreamElement(
                    element_type=ElementType.SMALL_TEXT,
                    tag="p",
                    content=unit.text,
                    bbox=unit.bbox,
                    page_num=page_index,
                    block_id=unit.block_id,
                    css_class="small",
                )
            )
        elif unit.tag.startswith("h"):
            out.append(
                StreamElement(
                    element_type=ElementType.HEADING,
                    tag=unit.tag,
                    content=unit.text,
                    bbox=unit.bbox,
                    page_num=page_index,
                    block_id=unit.block_id,
                    level=unit.level,
                )
            )
        else:
            out.append(
                StreamElement(
                    element_type=ElementType.PARAGRAPH,
                    tag="p",
                    content=unit.text,
                    bbox=unit.bbox,
                    page_num=page_index,
                    block_id=unit.block_id,
                )
            )
    flush_code()
    return out


def extract_tables(
    lines: list[ClassifiedLine], profile: DocumentFontProfile, page_index: int
) -> tuple[list[StreamElement], list[ClassifiedLine]]:
    """Rebuild proven table grids as BLOCK elements (remediation Fix 10).

    Tier-1 table pages exist: staggered cells fall under the router's
    columnar-overlap threshold and score high. Only the geometry the
    strict region proves becomes a table -- aligned pairs stay prose
    (they are indistinguishable from columns), and a grid the builder
    cannot explain keeps every line for the paragraph path.
    """
    if not lines:
        return [], lines
    bboxes = [ln.bbox for ln in lines]
    sizes = [ln.size for ln in lines]
    line_height = profile.line_height or (profile.body_size * 1.2)
    strict = table_region(bboxes, sizes, pad=0.0, overlap_limit=3.0 * line_height)
    if strict is None:
        return [], lines
    table_lines = [
        ln for ln in lines
        if in_table_region(strict, ln.bbox) and ln.raw_text.strip()
    ]
    if len(table_lines) < 2:
        return [], lines
    html, strays = build_table_html(
        [
            {"bbox": ln.bbox, "text": ln.text, "bold": ln.bold, "_line": ln}
            for ln in table_lines
        ],
        size_hint=sizes[0] if sizes else 10.0,
        already_escaped=True,
    )
    if html is None:
        return [], lines
    table = StreamElement(
        element_type=ElementType.BLOCK,
        tag="table",
        content=html,
        bbox=(0.0, strict[0], 0.0, strict[1]),
        page_num=page_index,
        block_id=-1,
    )
    consumed = {id(ln) for ln in table_lines}
    stray_lines = [d["_line"] for d in strays]
    rest = [ln for ln in lines if id(ln) not in consumed] + stray_lines
    rest.sort(key=lambda ln: (round(ln.bbox[1], 1), round(ln.bbox[0], 1)))
    return [table], rest


def build_page_stream(
    page: "fitz.Page",
    profile: DocumentFontProfile,
    page_index: int,
    spool_dir: str | None = None,
) -> list[StreamElement]:
    lines = classify_page(page, profile)
    tables, lines = extract_tables(lines, profile, page_index)
    units = build_paragraphs(lines, profile)
    elements = _collect_code_blocks(units, page_index, profile.line_height)
    elements.extend(extract_images(page, page_index, lines, spool_dir))
    elements.extend(tables)
    # Restore spatial order: images were appended after text.
    elements.sort(key=lambda e: (round(e.bbox[1], 1), round(e.bbox[0], 1)))
    return elements


def build_document_stream(
    doc: "fitz.Document",
    profile: DocumentFontProfile,
    page_indices: list[int] | None = None,
    spool_dir: str | None = None,
) -> dict[int, list[StreamElement]]:
    """Return ``{page_index: [StreamElement, ...]}`` for the requested pages."""
    targets = range(len(doc)) if page_indices is None else page_indices
    return {i: build_page_stream(doc[i], profile, i, spool_dir) for i in targets}


# Backwards-compatible convenience wrapper.
def convert_page(
    page: "fitz.Page", profile: DocumentFontProfile, page_index: int | None = None
) -> list[StreamElement]:
    idx = page.number if page_index is None else page_index
    return build_page_stream(page, profile, idx)
