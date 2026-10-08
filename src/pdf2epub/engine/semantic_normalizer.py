"""Deterministic semantic normalization (remediation Fix 4 + 5 + 6).

A focused pass-module in the ``heading_signals`` pattern: it runs on the
merged, welded stream after interpretation and before packaging, and
it only normalizes evidence already present in the stream -- it never
invents content.

``build_lists`` converts runs of clearly marked paragraphs into
semantic ``<ol>/<ul>`` blocks (single isolated markers stay prose, per
the plan's "do not convert isolated occurrences" rule; sub-rank markers
-- letter bullets and enumerators -- nest into the preceding ordered
item when the sequence resumes after them).

``linkify_urls`` turns unambiguous ``http(s)://`` text into anchors,
exactly once, stripping only sentence punctuation that provably sits
outside the URL.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .tier1_classifier import ElementType, StreamElement

__all__ = ["normalize_semantics", "build_lists", "linkify_urls"]


# ---------------------------------------------------------------------------
# URL detection (Fix 5)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<]+", re.IGNORECASE)
_TRAILING_SENTENCE_PUNCT = ".,;:!?'\"\u201d\u2019"


def _linkify_text(text: str) -> str:
    def repl(m: re.Match) -> str:
        url = m.group(0)
        stripped = url.rstrip(_TRAILING_SENTENCE_PUNCT)
        # a ')' belongs to the sentence unless the URL opened one
        while stripped.endswith(")") and stripped.count("(") < stripped.count(")"):
            stripped = stripped[:-1]
        trailing = url[len(stripped):]
        if len(stripped) <= len("https://x"):
            return url  # nothing URL-shaped survived the strip
        # content is already-escaped XHTML: the URL may legitimately
        # carry & entities and must not be re-escaped here.
        return f'<a href="{stripped}">{stripped}</a>{trailing}'

    return _URL_RE.sub(repl, text)


def _tag_parts(content: str) -> list[str]:
    return re.split(r"(<[^>]+>)", content)


def _element_accepts_links(e: StreamElement) -> bool:
    return e.element_type is ElementType.PARAGRAPH or (
        e.element_type is ElementType.BLOCK and e.tag in ("ul", "ol", "table")
    )


def linkify_urls(stream: list[StreamElement]) -> list[StreamElement]:
    out: list[StreamElement] = []
    for e in stream:
        if not _element_accepts_links(e) or "http" not in e.content.lower():
            out.append(e)
            continue
        parts = _tag_parts(e.content)
        in_link = False
        for i, part in enumerate(parts):
            if part.startswith("<"):
                if part.startswith("<a ") or part.startswith("<a>"):
                    in_link = True
                elif part == "</a>":
                    in_link = False
                continue
            if in_link:
                continue  # never wrap an existing anchor's text again
            parts[i] = _linkify_text(part)
        out.append(replace(e, content="".join(parts)))
    return out


# ---------------------------------------------------------------------------
# List reconstruction (Fix 6)
# ---------------------------------------------------------------------------

# Tier-1 can wrap a marker glyph in inline markup (a Wingdings 'o' bullet
# that registers as monospace becomes <code>o</code>), so every marker
# regex tolerates zero or more inline tags around the marker itself.
_TAG = r"(?:<[^>]+>)*"

# digits: "1." "12)" -- the only markers trusted as ordered evidence
_ORDERED_RE = re.compile(rf"^\s*{_TAG}(\d{{1,3}}){_TAG}[.)]\s+(.*)$", re.DOTALL)
# glyph bullets: literal bullet art, dashes used as bullets
_BULLET_RE = re.compile(
    rf"^\s*{_TAG}([^\w\s()\"'&,.;:!?]){_TAG}\s+(.*)$", re.DOTALL
)
# enumerators: a single letter or a roman numeral with a dot -- rendered
# unordered in v1, only legal as a nested run inside an ordered item
_ENUM_RE = re.compile(
    rf"^\s*{_TAG}([ivx]{{1,4}}|[a-z]){_TAG}[.)]\s+([a-z(].*)$", re.IGNORECASE
)
# bare lowercase letter + space: Wingdings-style 'o' bullets. Only ever
# accepted as a nested run directly inside an ordered item, never as a
# standalone opener -- "a lot of text" must stay a paragraph.
_LETTER_BULLET_RE = re.compile(rf"^\s*{_TAG}([a-z]){_TAG}\s+([a-z(].*)$")


def _classify_item(content: str) -> tuple[str, int | None, str] | None:
    """(kind, ordered_number, item_html) or None when not a list item.

    kind: "ol" (digits) / "ul" (glyph) / "sub" (enumerator or letter
    bullet -- nested-rank markers).
    """
    m = _ORDERED_RE.match(content)
    if m:
        return "ol", int(m.group(1)), m.group(2)
    m = _BULLET_RE.match(content)
    if m:
        return "ul", None, m.group(2)
    m = _ENUM_RE.match(content)
    if m:
        return "sub", None, m.group(2)
    m = _LETTER_BULLET_RE.match(content)
    if m:
        return "sub", None, m.group(2)
    return None


def _li(inner: str) -> str:
    return f"<li>{inner.strip()}</li>"


def _ol_element(items: list[dict], page_num: int) -> StreamElement:
    body = ""
    for item in items:
        inner = item["inner"].strip()
        if item["nest"]:
            inner += "<ul>" + "".join(_li(s) for s in item["nest"]) + "</ul>"
        body += _li(inner)
    start_attr = "" if items[0]["num"] == 1 else f' start="{items[0]["num"]}"'
    return StreamElement(
        element_type=ElementType.BLOCK, tag="ol",
        content=body.strip(),
        attrs=start_attr,
        page_num=page_num, block_id=0,
    )


def _ul_element(inners: list[str], page_num: int) -> StreamElement:
    return StreamElement(
        element_type=ElementType.BLOCK, tag="ul",
        content="".join(_li(inner) for inner in inners),
        page_num=page_num, block_id=0,
    )


def _is_paragraph(stream: list[StreamElement], i: int) -> bool:
    return i < len(stream) and stream[i].element_type is ElementType.PARAGRAPH


# A wrapped line tail: the previous collected text ends mid-sentence
# (no terminal punctuation) and this one opens lowercase. A colon does
# not terminate: it is how ordered items introduce their sub-bullets.
_TERMINAL = ".!?"


def _is_continuation(prev_inner: str, content: str) -> bool:
    prev = prev_inner.rstrip()
    nxt = content.lstrip()
    if not prev or not nxt:
        return False
    if prev[-1] in _TERMINAL:
        return False
    return nxt[0].islower()


def build_lists(stream: list[StreamElement]) -> list[StreamElement]:
    """Marker runs become semantic lists; everything else is untouched."""
    out: list[StreamElement] = []
    i = 0
    n = len(stream)
    while i < n:
        e = stream[i]
        if e.element_type is not ElementType.PARAGRAPH:
            out.append(e)
            i += 1
            continue

        classified = _classify_item(e.content)
        if classified is None or classified[0] == "sub":
            out.append(e)
            i += 1
            continue

        # -- ordered run: digit-marked items, non-decreasing -----------
        if classified[0] == "ol":
            consumed = [e]
            items: list[dict] = [
                {"num": classified[1], "inner": classified[2], "nest": []}
            ]
            i += 1
            # sub-rank markers directly under the last item: they nest
            # when the sequence resumes (or ends) right after them
            pending_subs: list[str] = []
            while _is_paragraph(stream, i):
                nxt = stream[i]
                c2 = _classify_item(nxt.content)
                if c2 and c2[0] == "ol" and c2[1] >= items[-1]["num"]:
                    items[-1]["nest"].extend(pending_subs)
                    pending_subs = []
                    items.append(
                        {"num": c2[1], "inner": c2[2], "nest": []}
                    )
                    consumed.append(nxt)
                    i += 1
                    continue
                if c2 and c2[0] == "sub":
                    pending_subs.append(c2[2])
                    consumed.append(nxt)
                    i += 1
                    continue
                # a wrapped tail belongs to the item or sub before it
                if not c2 and pending_subs and _is_continuation(
                    pending_subs[-1], nxt.content
                ):
                    pending_subs[-1] += " " + nxt.content.strip()
                    consumed.append(nxt)
                    i += 1
                    continue
                if not c2 and _is_continuation(items[-1]["inner"], nxt.content):
                    items[-1]["inner"] += " " + nxt.content.strip()
                    consumed.append(nxt)
                    i += 1
                    continue
                break
            if len(items) >= 2:
                items[-1]["nest"].extend(pending_subs)
                out.append(_ol_element(items, e.page_num))
            else:
                # an isolated occurrence never becomes a list
                out.extend(consumed)
            continue

        # -- glyph bullet run ------------------------------------------
        inners = [classified[2]]
        consumed = [e]
        i += 1
        while _is_paragraph(stream, i):
            nxt = stream[i]
            c2 = _classify_item(nxt.content)
            if c2 and c2[0] == "ul":
                inners.append(c2[2])
                consumed.append(nxt)
                i += 1
                continue
            if not c2 and _is_continuation(inners[-1], nxt.content):
                inners[-1] += " " + nxt.content.strip()
                consumed.append(nxt)
                i += 1
                continue
            break
        if len(inners) >= 2:
            out.append(_ul_element(inners, e.page_num))
        else:
            out.extend(consumed)
    return out


def normalize_semantics(stream: list[StreamElement]) -> list[StreamElement]:
    """The single normalizer boundary: structure first, inline links last."""
    return linkify_urls(build_lists(stream))
