"""
Module 3: Rich-Context AI Semantic Engine (Tier 2)
==================================================

Handles pages that fail Module 2's deterministic checks: multi-column flows,
sidebars, table-heavy layouts, scanned rasters, corrupted CMaps.

Design commitments
------------------
* The model never receives flat ``get_text("text")``. It receives either a 2D
  layout digest (bbox + typography per line) or a 150 DPI page raster.
* The cache key is composite: payload + system prompt + model id + temperature
  + schema version. Editing a prompt invalidates the cache instantly.
* Every model response passes an XHTML sanitise/repair gate before it is
  allowed anywhere near the EPUB container.
* A short batch response is repaired by re-prompting page by page, then by
  falling back to a deterministic render of the digest. The pipeline never
  dies on a ragged array.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("tier2")

SCHEMA_VERSION = "xhtml-pages/v2"
DEFAULT_CACHE_DIR = Path(".cache_llm_epub")

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TEXT_SYSTEM_PROMPT = """You are an expert eBook compiler and layout engineer.
You receive a 2D spatial layout digest of PDF page lines: line ids, block ids,
bounding boxes [x0, y0, x1, y1], font sizes, bold/italic flags and text.
Convert it into clean, semantic XHTML body content.

Strict rules:
1. Reconstruct natural reading order from the bounding boxes. Read a column
   fully top-to-bottom before moving to the next column.
2. Group sidebars, callouts and pull-quotes into <aside> or <blockquote>.
3. Merge wrapped lines into complete <p> paragraphs. Never split a sentence
   across two tags.
4. Render tabular material as <table> with <thead>, <tbody>, <tr>, <th>, <td>.
5. Strip running headers, running footers and standalone page numbers.
6. Use ONLY these block tags: h1, h2, h3, h4, p, blockquote, aside, pre, table,
   thead, tbody, tr, th, td, ul, ol, li, figure, figcaption.
   Use ONLY strong, em, code, span, br for inline content.
7. Escape &, < and > as &amp;, &lt;, &gt;. Close every tag. Self-close voids
   as <br/>.
8. Return raw JSON only, no markdown fences, matching:
   {"xhtml_pages": ["<p>page 1 ...</p>", "<p>page 2 ...</p>"]}
   The array length MUST equal the number of input pages, in the same order.
"""

VISION_SYSTEM_PROMPT = """You are an expert eBook OCR and accessibility engineer.
You are given a 150 DPI image of a single book page. Transcribe it into valid,
semantic XHTML body content.

Strict rules:
1. Transcribe all readable text accurately. Do not invent content.
2. Structure headings (h1-h4), paragraphs (p) and lists (ul/ol/li).
3. Render tables as <table> with <tr>/<th>/<td>.
4. Give every <img> you emit a meaningful alt attribute.
5. Strip running headers, running footers and standalone page numbers.
6. Output must be XHTML: all tags closed, entities escaped, voids self-closed.
7. Return raw JSON only, no markdown fences:
   {"xhtml_pages": ["<p>...</p>"]}
"""

REPAIR_PROMPT_SUFFIX = """

The previous attempt produced invalid output. Validator message:
{error}
Return corrected XHTML that resolves this exact problem. Same JSON schema.
"""


# ---------------------------------------------------------------------------
# XHTML sanitise & repair gate
# ---------------------------------------------------------------------------

ALLOWED_BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "aside", "pre",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "ul", "ol", "li", "dl", "dt", "dd", "figure", "figcaption", "section",
    "div", "hr",
}
ALLOWED_INLINE_TAGS = {"strong", "em", "code", "span", "br", "sup", "sub", "a", "img", "b", "i"}
ALLOWED_TAGS = ALLOWED_BLOCK_TAGS | ALLOWED_INLINE_TAGS

FENCE_OPEN_RE = re.compile(r"^\s*```(?:xml|html|xhtml|json)?\s*", re.IGNORECASE)
FENCE_CLOSE_RE = re.compile(r"\s*```\s*$")
BAD_AMP_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")
VOID_RE = re.compile(r"<(img|br|hr|meta|link)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)/?>", re.IGNORECASE)
DISALLOWED_BLOCK_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|form|input|button)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)


def _normalise_voids(html: str) -> str:
    def repl(m: re.Match) -> str:
        tag, attrs = m.group(1), m.group(2).rstrip()
        attrs = (" " + attrs.strip()) if attrs.strip() else ""
        return f"<{tag}{attrs}/>"

    return VOID_RE.sub(repl, html)


def _strip_disallowed_tags(html: str) -> str:
    html = DISALLOWED_BLOCK_RE.sub("", html)

    def unwrap(m: re.Match) -> str:
        name = m.group(2).lower()
        return m.group(0) if name in ALLOWED_TAGS else ""

    return re.sub(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>", unwrap, html)


def _lxml_repair(html: str) -> str | None:
    """Tolerant HTML parse + XML re-serialise. Keeps structure, unlike regex."""
    try:
        from lxml import etree, html as lhtml
    except ImportError:  # pragma: no cover
        return None
    try:
        fragment = lhtml.fragment_fromstring(html, create_parent="div")
        parts = []
        if fragment.text:
            parts.append(escape(fragment.text, quote=False))
        for child in fragment:
            parts.append(etree.tostring(child, encoding="unicode", method="xml"))
        out = "".join(parts).strip()
        return out or None
    except Exception:
        return None


def is_well_formed(html: str) -> tuple[bool, str]:
    wrapper = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<root xmlns="http://www.w3.org/1999/xhtml">' + html + "</root>"
    )
    try:
        ET.fromstring(wrapper)
        return True, ""
    except ET.ParseError as exc:
        return False, str(exc)


def sanitize_and_validate_xhtml(raw_html: str) -> str:
    """Return well-formed XHTML, repairing what can be repaired.

    Escalation ladder: fence strip -> entity fix -> void normalisation ->
    tag whitelist -> lxml structural repair -> plain-text fallback.
    """
    if not raw_html or not raw_html.strip():
        return ""

    html = raw_html.strip()
    html = FENCE_OPEN_RE.sub("", html)
    html = FENCE_CLOSE_RE.sub("", html)
    html = BAD_AMP_RE.sub("&amp;", html)
    html = _normalise_voids(html)
    html = _strip_disallowed_tags(html)

    ok, _ = is_well_formed(html)
    if ok:
        return html.strip()

    repaired = _lxml_repair(html)
    if repaired:
        repaired = BAD_AMP_RE.sub("&amp;", repaired)
        ok, _ = is_well_formed(repaired)
        if ok:
            return repaired.strip()

    # Last resort: keep the words, drop the broken markup.
    text = re.sub(r"<[^>]*>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [escape(l.strip(), quote=False) for l in text.splitlines() if l.strip()]
    return "\n".join(f"<p>{l}</p>" for l in lines)


# ---------------------------------------------------------------------------
# Composite cache key
# ---------------------------------------------------------------------------


def get_cache_key(
    payload_str: str,
    system_prompt: str,
    model_id: str,
    temperature: float,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    composite = "||".join(
        [payload_str, system_prompt, model_id, f"{temperature!r}", schema_version]
    )
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@dataclass
class Tier2Request:
    page_num: int  # 1-based
    layout_digest: list[dict] | None = None
    raster_bytes: bytes | None = None
    page_width: float = 0.0  # physical page width in points, for the digest fallback

    @property
    def is_vision(self) -> bool:
        return self.raster_bytes is not None

    def payload_fingerprint(self) -> str:
        if self.is_vision:
            assert self.raster_bytes is not None
            return "raster:" + hashlib.sha256(self.raster_bytes).hexdigest()
        return "digest:" + hashlib.sha256(
            json.dumps(self.layout_digest or [], sort_keys=True).encode("utf-8")
        ).hexdigest()


# LLM client contract:
#   client(system_prompt: str, user_payload: str, image_b64: str | None) -> str
LLMClient = Callable[[str, str, "str | None"], str]


# ---------------------------------------------------------------------------
# Deterministic fallbacks (offline / mock mode)
# ---------------------------------------------------------------------------


TWO_COLUMN_SPREAD_FRACTION = 0.18  # fraction of page width that counts as a gutter


def _detect_two_column(digest: list[dict], page_width: float) -> tuple[bool, float]:
    """Column split, normalised to page width rather than a fixed point value.

    A fixed ``spread > 100pt`` threshold misfires differently on a mass-market
    paperback (~300pt wide) than on a letter-size PDF (~612pt wide). Falling
    back to the widest observed line when the caller has no page dimensions
    (e.g. hand-built digests in unit tests) keeps this usable without one.
    """
    xs = [d["bbox"][0] for d in digest]
    if not xs:
        return False, 0.0
    midpoint = (min(xs) + max(xs)) / 2
    spread = max(xs) - min(xs)
    pw = page_width or max((d["bbox"][2] for d in digest), default=0.0) or 612.0
    return spread > (TWO_COLUMN_SPREAD_FRACTION * pw), midpoint


def _column_of(d: dict, two_col: bool, midpoint: float) -> int:
    return 1 if (two_col and d["bbox"][0] > midpoint) else 0


def _modal_line_height(digest: list[dict]) -> float:
    """Mode of same-block vertical gaps, computed from this page alone.

    Mirrors ``DocumentFontProfile``'s 0.5pt bucketing (raw float gaps rarely
    repeat exactly), but unlike that profile this has only one page of data
    to work with, so a page dominated by a single heading-to-body transition
    can skew the mode. That is an accepted approximation for an offline
    fallback that a real model call would otherwise replace entirely.
    """
    by_block: dict[object, list[dict]] = {}
    for d in digest:
        by_block.setdefault(d.get("block_id", 0), []).append(d)

    gaps: Counter = Counter()
    for lines in by_block.values():
        ordered = sorted(lines, key=lambda d: d["bbox"][3])
        prev_baseline = None
        for d in ordered:
            baseline = d["bbox"][3]  # bottom edge, used as a baseline proxy
            if prev_baseline is not None:
                gap = baseline - prev_baseline
                if 0 < gap < 100:
                    gaps[round(gap * 2) / 2] += 1
            prev_baseline = baseline
    if gaps:
        return gaps.most_common(1)[0][0]
    sizes = [d["size"] for d in digest]
    body = max(set(sizes), key=sizes.count) if sizes else 10.0
    return body * 1.2


def _block_right_margins(digest: list[dict]) -> dict[object, float]:
    """75th-percentile right edge per block - stable against one long line.

    Same idea as ``tier1_classifier.block_right_margin``, rewritten against
    the digest's raw bbox fields: this fallback has no ``ClassifiedLine`` or
    ``DocumentFontProfile`` to call the real helper on.
    """
    by_block: dict[object, list[float]] = {}
    for d in digest:
        by_block.setdefault(d.get("block_id", 0), []).append(d["bbox"][2])
    margins = {}
    for block_id, edges in by_block.items():
        ordered = sorted(edges)
        idx = int(0.75 * (len(ordered) - 1))
        margins[block_id] = ordered[idx]
    return margins


def _join_hyphenated(a: str, b: str) -> str:
    if a.endswith("-") and not a.endswith("--") and b[:1].islower():
        return a[:-1] + b
    return a.rstrip() + " " + b.lstrip()


def _merge_digest_lines(
    ordered: list[dict],
    two_col: bool,
    midpoint: float,
    line_height: float,
    margins: dict[object, float],
) -> list[dict]:
    """Merge wrapped lines into paragraph-level dicts, digest-native.

    Deliberately drops Tier 1's "would the next word fit" refinement: that
    check needs a real glyph-derived ``first_word_width``, which the digest
    does not carry (only per-line ``size``, not per-word metrics). Estimating
    it from character count would bias the wrap decision for proportional
    and CJK fonts. Right-margin proximity alone is the honest signal this
    data actually supports.
    """
    merged: list[dict] = []
    buffer: dict | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer is not None:
            merged.append(buffer)
        buffer = None

    for d in ordered:
        if buffer is None:
            buffer = dict(d)
            continue

        same_block = d.get("block_id", 0) == buffer.get("block_id", 0)
        same_column = _column_of(d, two_col, midpoint) == _column_of(buffer, two_col, midpoint)
        vertical_gap = d["bbox"][1] - buffer["bbox"][1]
        lh = line_height or (buffer["size"] * 1.2)
        same_flow = 0 < vertical_gap and abs(vertical_gap - lh) < (lh * 0.35)
        size_match = abs(d["size"] - buffer["size"]) < 0.6
        margin = margins.get(buffer.get("block_id", 0), 0.0)
        near_margin = margin > 0 and (margin - buffer["bbox"][2]) < max(buffer["size"] * 0.5, 3.0)

        if same_block and same_column and same_flow and size_match and near_margin:
            buffer["text"] = _join_hyphenated(buffer["text"], d["text"])
            # Advance the trailing edge (top AND bottom) to the line just
            # merged, not the paragraph's origin - comparing every new line
            # against the origin makes the gap grow by one line height per
            # row, which silently truncates every paragraph after its
            # second line (same failure mode tier1_classifier.build_paragraphs
            # documents for buffer_last_bbox).
            buffer["bbox"] = (buffer["bbox"][0], d["bbox"][1], d["bbox"][2], d["bbox"][3])
        else:
            flush()
            buffer = dict(d)
    flush()
    return merged


def _digest_fallback(req: Tier2Request) -> str:
    """Sort the digest into a reading order, merge wrapped lines, emit XHTML.

    Column-aware: group lines by block, order blocks by (column band, y),
    then merge same-block/same-column lines whose vertical gap and right-edge
    proximity look like a wrapped paragraph (the same 75th-percentile margin
    test Tier 1 uses, rewritten against the digest's own bbox fields). Not as
    good as a model, but a real step up from one <p> per raw line, and never
    worse than dropping the page.
    """
    digest = req.layout_digest or []
    if not digest:
        return f"<!-- tier2 digest fallback: page {req.page_num} empty -->"

    two_col, midpoint = _detect_two_column(digest, req.page_width)
    line_height = _modal_line_height(digest)
    margins = _block_right_margins(digest)

    ordered = sorted(
        digest, key=lambda d: (_column_of(d, two_col, midpoint), d["bbox"][1], d["bbox"][0])
    )
    paragraphs = _merge_digest_lines(ordered, two_col, midpoint, line_height, margins)

    out: list[str] = []
    sizes = [d["size"] for d in digest]
    body = max(set(sizes), key=sizes.count) if sizes else 10.0
    for d in paragraphs:
        text = escape(d["text"], quote=False)
        ratio = d["size"] / body if body else 1.0
        if ratio >= 1.6:
            out.append(f"<h1>{text}</h1>")
        elif ratio >= 1.3:
            out.append(f"<h2>{text}</h2>")
        elif ratio >= 1.15:
            out.append(f"<h3>{text}</h3>")
        else:
            out.append(f"<p>{text}</p>")
    return "\n".join(out)


def _vision_fallback(req: Tier2Request) -> str:
    return (
        f"<!-- tier2 vision fallback: page {req.page_num} has no text layer -->\n"
        f"<p>[Page {req.page_num}: image-only page. No OCR model configured; "
        f"run with an API key to transcribe.]</p>"
    )


# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------


class Tier2Handler:
    def __init__(
        self,
        llm_client_fn: LLMClient | None = None,
        model_id: str = "gpt-4o",
        temperature: float = 0.0,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        max_retries: int = 2,
        retry_backoff: float = 1.5,
    ) -> None:
        self.llm_client_fn = llm_client_fn
        self.model_id = model_id
        self.temperature = temperature
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.stats = {"cache_hits": 0, "api_calls": 0, "repairs": 0, "fallbacks": 0}

    # -- cache -------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _cache_read(self, key: str) -> list[str] | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)["xhtml_pages"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _cache_write(self, key: str, pages: list[str]) -> None:
        tmp = self._cache_path(key).with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump({"xhtml_pages": pages, "model": self.model_id}, fh, indent=2)
            tmp.replace(self._cache_path(key))
        except OSError:  # pragma: no cover
            log.warning("cache write failed for %s", key)

    # -- transport ---------------------------------------------------------
    def _call_model(
        self, system_prompt: str, payload: str, image_b64: str | None = None
    ) -> list[str]:
        assert self.llm_client_fn is not None
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                self.stats["api_calls"] += 1
                raw = self.llm_client_fn(system_prompt, payload, image_b64)
                parsed = json.loads(_strip_json_fences(raw))
                pages = parsed.get("xhtml_pages")
                if not isinstance(pages, list):
                    raise ValueError("response missing 'xhtml_pages' array")
                return [str(p) for p in pages]
            except Exception as exc:  # network, JSON, schema - all retryable
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("tier2 call failed (attempt %s): %s", attempt + 1, last_error)
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff ** attempt)
        raise RuntimeError(f"Tier 2 model call failed after retries: {last_error}")

    # -- public API --------------------------------------------------------
    def process_batch(self, requests: list[Tier2Request]) -> list[str]:
        if not requests:
            return []
        if any(r.is_vision for r in requests):
            vision = [r for r in requests if r.is_vision]
            digest = [r for r in requests if not r.is_vision]
            by_page: dict[int, str] = {}
            for r, html in zip(vision, self._process_vision(vision)):
                by_page[r.page_num] = html
            for r, html in zip(digest, self._process_digest_batch(digest)):
                by_page[r.page_num] = html
            return [by_page[r.page_num] for r in requests]
        return self._process_digest_batch(requests)

    # -- vision path -------------------------------------------------------
    def _process_vision(self, requests: list[Tier2Request]) -> list[str]:
        results: list[str] = []
        for req in requests:
            key = get_cache_key(
                req.payload_fingerprint(),
                VISION_SYSTEM_PROMPT,
                self.model_id,
                self.temperature,
            )
            cached = self._cache_read(key)
            if cached:
                self.stats["cache_hits"] += 1
                results.append(cached[0])
                continue

            if self.llm_client_fn is None:
                self.stats["fallbacks"] += 1
                html = _vision_fallback(req)
            else:
                assert req.raster_bytes is not None
                img_b64 = base64.b64encode(req.raster_bytes).decode("ascii")
                try:
                    pages = self._call_model(
                        VISION_SYSTEM_PROMPT,
                        f"Transcribe page {req.page_num} into XHTML.",
                        img_b64,
                    )
                    html = sanitize_and_validate_xhtml(pages[0] if pages else "")
                except RuntimeError as exc:
                    log.error("vision page %s failed: %s", req.page_num, exc)
                    self.stats["fallbacks"] += 1
                    html = _vision_fallback(req)

            self._cache_write(key, [html])
            results.append(html)
        return results

    # -- digest path -------------------------------------------------------
    def _batch_payload(self, requests: list[Tier2Request]) -> str:
        return json.dumps(
            {
                "instruction": "Convert each page layout digest into semantic XHTML.",
                "page_count": len(requests),
                "pages": [
                    {"page_num": r.page_num, "layout_digest": r.layout_digest or []}
                    for r in requests
                ],
            },
            sort_keys=True,
        )

    def _process_digest_batch(self, requests: list[Tier2Request]) -> list[str]:
        if not requests:
            return []

        payload = self._batch_payload(requests)
        key = get_cache_key(payload, TEXT_SYSTEM_PROMPT, self.model_id, self.temperature)
        cached = self._cache_read(key)
        if cached and len(cached) == len(requests):
            self.stats["cache_hits"] += 1
            return cached

        if self.llm_client_fn is None:
            self.stats["fallbacks"] += len(requests)
            pages = [_digest_fallback(r) for r in requests]
            self._cache_write(key, pages)
            return pages

        try:
            raw_pages = self._call_model(TEXT_SYSTEM_PROMPT, payload, None)
        except RuntimeError as exc:
            log.error("digest batch failed: %s", exc)
            self.stats["fallbacks"] += len(requests)
            return [_digest_fallback(r) for r in requests]

        if len(raw_pages) != len(requests):
            log.warning(
                "batch length mismatch: expected %s, got %s - re-prompting per page",
                len(requests),
                len(raw_pages),
            )
            self.stats["repairs"] += 1
            pages = [self._process_single_digest(r) for r in requests]
        else:
            pages = [sanitize_and_validate_xhtml(p) for p in raw_pages]

        self._cache_write(key, pages)
        return pages

    def _process_single_digest(self, req: Tier2Request) -> str:
        payload = self._batch_payload([req])
        key = get_cache_key(payload, TEXT_SYSTEM_PROMPT, self.model_id, self.temperature)
        cached = self._cache_read(key)
        if cached:
            self.stats["cache_hits"] += 1
            return cached[0]
        try:
            pages = self._call_model(TEXT_SYSTEM_PROMPT, payload, None)
            html = sanitize_and_validate_xhtml(pages[0] if pages else "")
        except RuntimeError:
            self.stats["fallbacks"] += 1
            html = _digest_fallback(req)
        self._cache_write(key, [html])
        return html

    # -- self-repair -------------------------------------------------------
    def repair_page(self, req: Tier2Request, validator_error: str) -> str:
        """Re-prompt one page with the validator message injected."""
        base_prompt = VISION_SYSTEM_PROMPT if req.is_vision else TEXT_SYSTEM_PROMPT
        prompt = base_prompt + REPAIR_PROMPT_SUFFIX.format(error=validator_error[:1500])
        if self.llm_client_fn is None:
            return sanitize_and_validate_xhtml(
                _vision_fallback(req) if req.is_vision else _digest_fallback(req)
            )
        try:
            if req.is_vision:
                assert req.raster_bytes is not None
                img_b64 = base64.b64encode(req.raster_bytes).decode("ascii")
                pages = self._call_model(prompt, f"Fix page {req.page_num}.", img_b64)
            else:
                pages = self._call_model(prompt, self._batch_payload([req]), None)
            return sanitize_and_validate_xhtml(pages[0] if pages else "")
        except RuntimeError:
            self.stats["fallbacks"] += 1
            return _digest_fallback(req)


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


# Module-level convenience wrapper (keeps the original call signature working).
def process_tier2_batch(
    requests: list[Tier2Request],
    llm_client_fn: LLMClient | None = None,
    model_id: str = "gpt-4o",
    temperature: float = 0.0,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> list[str]:
    handler = Tier2Handler(
        llm_client_fn=llm_client_fn,
        model_id=model_id,
        temperature=temperature,
        cache_dir=cache_dir,
    )
    return handler.process_batch(requests)
