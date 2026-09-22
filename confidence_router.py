"""
Module 2: Pre-Conversion Triage & Layout Router
===============================================

A strict quality gate between the deterministic stream processor (Module 1) and
the AI semantic engine (Module 3).

Order of operations per page
----------------------------
1. Text sanity gate  - no text layer, PUA saturation, or gibberish token rate
                       forces the page onto the vision/OCR path immediately.
2. Layout scoring    - character-weighted font variance, reading-order
                       violations, vector-path density.
3. Asymmetric route  - a false negative (complex page sent to Tier 1) silently
                       corrupts the publication; a false positive only costs a
                       fraction of a cent. Thresholds are calibrated for FN~0.
4. Payload build     - complex pages leave with a 2D JSONL layout digest or a
                       150 DPI raster, never a flat text string.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


# ---------------------------------------------------------------------------
# Tunable calibration constants
# ---------------------------------------------------------------------------

TIER1_THRESHOLD = 85            # score >= this goes to the heuristic engine
PUA_RATIO_LIMIT = 0.15          # private-use / control character saturation
MIN_TOKENS_FOR_LEXICAL = 30     # below this a page is too short to judge
STOPWORD_HIT_FLOOR = 0.08       # real English prose sits at 0.35-0.50
FONT_SIGMA_THRESHOLD = 3.5
ORDER_JUMP_DY = -20.0
ORDER_JUMP_DX = 50.0
VECTOR_DENSITY_THRESHOLD = 20
RASTER_DPI = 150
FURNITURE_BAND = 0.10   # top/bottom 10%: headers, footers, folios
MIN_LINE_CHARS = 4      # a lone folio is not a reading-order signal


class RoutingTarget(Enum):
    TIER1_HEURISTIC = auto()
    TIER2_LLM_DIGEST = auto()
    TIER2_VISION_OCR = auto()


@dataclass
class PageConfidenceReport:
    page_num: int                  # 1-based, for humans
    page_index: int                # 0-based, for indexing
    score: int
    target: RoutingTarget
    has_text: bool = True
    cmap_corrupted: bool = False
    dictionary_hit_rate: float = 0.0
    font_variance: float = 0.0     # population std-dev of span sizes
    order_violations: int = 0
    vector_count: int = 0
    penalties: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    layout_digest: list[dict] | None = None
    raster_bytes: bytes | None = None

    @property
    def is_tier1(self) -> bool:
        return self.target is RoutingTarget.TIER1_HEURISTIC


# ---------------------------------------------------------------------------
# 1. Text sanity gate (CMap corruption / mojibake detection)
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "it", "for",
    "not", "on", "with", "he", "as", "you", "do", "at", "this", "but", "his",
    "by", "from", "they", "we", "say", "her", "she", "or", "an", "will", "my",
    "one", "all", "would", "there", "their", "what", "so", "up", "out", "if",
    "about", "who", "get", "which", "go", "me", "when", "make", "can", "like",
    "time", "no", "just", "him", "know", "take", "people", "into", "year",
    "your", "good", "some", "could", "them", "see", "other", "than", "then",
    "now", "look", "only", "come", "its", "over", "think", "also", "back",
    "after", "use", "two", "how", "our", "work", "first", "well", "way",
    "even", "new", "want", "because", "any", "these", "give", "day", "most",
    "us", "is", "was", "are", "been", "has", "had", "were", "more", "such",
    "may", "each", "between", "through", "where", "must", "should", "while",
    "both", "same", "very", "here", "does", "did", "being", "his", "shall",
}

TOKEN_RE = re.compile(r"\b[a-zA-Z]{2,}\b")


@dataclass
class TextSanityResult:
    sane: bool
    hit_rate: float
    pua_ratio: float
    reason: str
    has_text: bool


def assess_text_sanity(text: str) -> TextSanityResult:
    """Pure function so the gate is unit-testable without a PDF fixture."""
    if not text or not text.strip():
        return TextSanityResult(False, 0.0, 0.0, "no_text_layer", False)

    total = len(text)
    pua = sum(
        1
        for c in text
        if 0xE000 <= ord(c) <= 0xF8FF
        or ord(c) == 0xFFFD
        or (ord(c) < 32 and c not in "\n\r\t")
    )
    pua_ratio = pua / total if total else 0.0
    if pua_ratio > PUA_RATIO_LIMIT:
        return TextSanityResult(False, 0.0, pua_ratio, "pua_saturation", True)

    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        return TextSanityResult(True, 0.0, pua_ratio, "no_alpha_tokens", True)

    hits = sum(1 for t in tokens if t in STOPWORDS)
    hit_rate = hits / len(tokens)

    if len(tokens) >= MIN_TOKENS_FOR_LEXICAL and hit_rate < STOPWORD_HIT_FLOOR:
        return TextSanityResult(False, hit_rate, pua_ratio, "lexical_gibberish", True)

    return TextSanityResult(True, hit_rate, pua_ratio, "ok", True)


def text_from_blocks(blocks: list[dict]) -> str:
    """Reconstruct page text from an already-extracted dict.

    Saves a second full ``get_text`` pass per page. On a 600 page book that is
    600 fewer extractions, which is a large share of the routing cost.
    """
    return "\n".join(
        "".join(sp.get("text", "") for sp in line["spans"])
        for b in blocks
        for line in b["lines"]
    )


def check_text_sanity(page: "fitz.Page") -> TextSanityResult:
    return assess_text_sanity(page.get_text("text"))


# ---------------------------------------------------------------------------
# 2. Structural signals
# ---------------------------------------------------------------------------


def weighted_font_sigma(blocks: list[dict]) -> float:
    spans = [
        s
        for b in blocks
        for line in b["lines"]
        for s in line["spans"]
        if s.get("text", "").strip()
    ]
    if not spans:
        return 0.0
    total = sum(len(s["text"].strip()) for s in spans)
    if total == 0:
        return 0.0
    mean = sum(s["size"] * len(s["text"].strip()) for s in spans) / total
    var = sum(len(s["text"].strip()) * (s["size"] - mean) ** 2 for s in spans) / total
    return math.sqrt(var)


def count_order_violations(blocks: list[dict], page_height: float = 0.0) -> int:
    """Backward Y jumps paired with a large X shift, over body content only.

    Running headers and footers are frequently emitted before or after the body
    blocks, which produces one huge backward jump on every page of a normal
    book. Counting those would send a clean single-column publication straight
    to the paid tier, so the furniture band is excluded from the metric.
    """
    prev_y: float | None = None
    prev_x: float | None = None
    violations = 0
    top_limit = page_height * FURNITURE_BAND if page_height else 0.0
    bottom_limit = page_height * (1 - FURNITURE_BAND) if page_height else float("inf")

    for b in blocks:
        for line in b["lines"]:
            text = "".join(s.get("text", "") for s in line["spans"]).strip()
            if len(text) < MIN_LINE_CHARS:
                continue
            top_y, left_x = line["bbox"][1], line["bbox"][0]
            if page_height and (top_y < top_limit or line["bbox"][3] > bottom_limit):
                continue
            if prev_y is not None and prev_x is not None:
                if (top_y - prev_y) < ORDER_JUMP_DY and abs(left_x - prev_x) > ORDER_JUMP_DX:
                    violations += 1
            prev_y, prev_x = top_y, left_x
    return violations


def build_layout_digest(page: "fitz.Page") -> list[dict]:
    """Compact JSONL-shaped payload: coordinates + typography, not flat text."""
    digest: list[dict] = []
    raw = page.get_text("dict")
    line_id = 0
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        block_id = block.get("number", 0)
        for line in block["lines"]:
            text = "".join(s.get("text", "") for s in line["spans"]).strip()
            if not text:
                continue
            line_id += 1
            dom = max(line["spans"], key=lambda s: len(s.get("text", "").strip()))
            digest.append(
                {
                    "line_id": line_id,
                    "block_id": block_id,
                    "bbox": [round(v, 1) for v in line["bbox"]],
                    "size": round(dom["size"], 1),
                    "bold": bool(dom.get("flags", 0) & (1 << 4)),
                    "italic": bool(dom.get("flags", 0) & (1 << 1)),
                    "text": text,
                }
            )
    return digest


def render_page_raster(page: "fitz.Page", dpi: int = RASTER_DPI) -> bytes:
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


# ---------------------------------------------------------------------------
# 3. Page evaluation
# ---------------------------------------------------------------------------


def score_page_layout(
    blocks: list[dict], vector_count: int, page_height: float = 0.0
) -> tuple[int, dict, float, int]:
    sigma = weighted_font_sigma(blocks)
    violations = count_order_violations(blocks, page_height)

    penalties: dict[str, int] = {"font_variance": 0, "reading_order": 0, "vector_density": 0}

    if sigma > FONT_SIGMA_THRESHOLD:
        penalties["font_variance"] = min(35, int((sigma - FONT_SIGMA_THRESHOLD) * 12))
    if violations > 0:
        # 20 (not 15) per violation: at 15 a single genuine two-column jump
        # lands on exactly 85 and slips back into the deterministic path.
        penalties["reading_order"] = min(45, violations * 20)
    if vector_count > VECTOR_DENSITY_THRESHOLD:
        penalties["vector_density"] = min(
            30, int((vector_count - VECTOR_DENSITY_THRESHOLD) * 1.5)
        )

    score = max(0, 100 - sum(penalties.values()))
    return score, penalties, sigma, violations


def evaluate_page(
    page: "fitz.Page", page_num: int, *, build_payloads: bool = False
) -> PageConfidenceReport:
    """Score one page.

    ``build_payloads`` is off by default. Building every digest and every
    150 DPI raster during triage means a 500 page scan materialises hundreds of
    megabytes of PNG before a single page has been converted. The driver builds
    payloads one batch at a time instead, and releases them straight after.
    """
    page_index = page_num - 1
    raw = page.get_text("dict")
    blocks = [b for b in raw["blocks"] if b.get("type") == 0]
    sanity = assess_text_sanity(text_from_blocks(blocks))
    vector_count = len(page.get_drawings())

    if not sanity.sane:
        return PageConfidenceReport(
            page_num=page_num,
            page_index=page_index,
            score=0,
            target=RoutingTarget.TIER2_VISION_OCR,
            has_text=sanity.has_text,
            cmap_corrupted=sanity.reason in ("pua_saturation", "lexical_gibberish"),
            dictionary_hit_rate=round(sanity.hit_rate, 3),
            vector_count=vector_count,
            reasons=[f"sanity:{sanity.reason}"],
            raster_bytes=render_page_raster(page) if build_payloads else None,
        )

    score, penalties, sigma, violations = score_page_layout(
        blocks, vector_count, float(page.rect.height)
    )

    reasons = [f"{k}:-{v}" for k, v in penalties.items() if v]
    if score >= TIER1_THRESHOLD:
        target = RoutingTarget.TIER1_HEURISTIC
        digest = None
    else:
        target = RoutingTarget.TIER2_LLM_DIGEST
        digest = build_layout_digest(page) if build_payloads else None

    return PageConfidenceReport(
        page_num=page_num,
        page_index=page_index,
        score=score,
        target=target,
        has_text=True,
        cmap_corrupted=False,
        dictionary_hit_rate=round(sanity.hit_rate, 3),
        font_variance=round(sigma, 2),
        order_violations=violations,
        vector_count=vector_count,
        penalties=penalties,
        reasons=reasons or ["clean"],
        layout_digest=digest,
    )


def attach_payload(page: "fitz.Page", report: PageConfidenceReport) -> PageConfidenceReport:
    """Build the Tier 2 payload for one page, just before it is needed."""
    if report.target is RoutingTarget.TIER2_VISION_OCR:
        if report.raster_bytes is None:
            report.raster_bytes = render_page_raster(page)
    elif report.target is RoutingTarget.TIER2_LLM_DIGEST:
        if report.layout_digest is None:
            report.layout_digest = build_layout_digest(page)
    return report


def release_payload(report: PageConfidenceReport) -> None:
    """Drop heavy payload data once the page has been converted."""
    report.raster_bytes = None
    report.layout_digest = None


def route_document(
    doc: "fitz.Document",
    *,
    build_payloads: bool = False,
    progress: "Callable[[int, int], None] | None" = None,
) -> list[PageConfidenceReport]:
    """Evaluate every page of an already-open document (no second file parse)."""
    total = len(doc)
    reports = []
    for i in range(total):
        reports.append(evaluate_page(doc[i], i + 1, build_payloads=build_payloads))
        if progress is not None:
            progress(i + 1, total)
    return reports


def summarise(reports: list[PageConfidenceReport]) -> dict[str, int]:
    out = {"tier1": 0, "tier2_digest": 0, "tier2_vision": 0}
    for r in reports:
        if r.target is RoutingTarget.TIER1_HEURISTIC:
            out["tier1"] += 1
        elif r.target is RoutingTarget.TIER2_LLM_DIGEST:
            out["tier2_digest"] += 1
        else:
            out["tier2_vision"] += 1
    return out
