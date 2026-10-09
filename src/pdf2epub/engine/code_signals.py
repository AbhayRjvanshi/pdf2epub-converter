"""Fix 9: deterministic code detection for non-monospace listings.

The monospace path (``all_mono`` in ``classify_page``) already
recognizes listings set in a fixed-pitch font. This module closes the
blind spot: code printed in a *proportional* font, which a human
recognizes from syntax, indentation and statement sequence.

Design (remediation plan, Fix 9 review):

* **Evidence before inference.** Every line is scored by explicit,
  explainable signals: keyword statements, assignments, call shapes,
  comment markers, block punctuation (strong); trailing continuations
  and operator density (weak); URLs, list markers and sentence-shaped
  prose (negative).
* **Negatives have precedence.** A URL-only line or a list-marker line
  never *initiates* code, and sentence-shaped prose is never absorbed
  into a run -- but negatives do not veto *continuation* of an already
  established, geometry-compatible block (a URL string constant can
  legitimately live inside a listing).
* **Runs, not lines.** Two consecutive strong lines with compatible
  geometry may qualify; three-plus weaker lines may qualify as a
  combined run; a preceding label ("Example implementation:")
  strengthens a candidate but never establishes a block alone.
* **One pass, bounded lookahead.** O(N) over the page's lines; no
  whole-document rescans, no rasterization, no model calls.

Detection runs in ``classify_page`` BEFORE structural-heading
promotion, so title-cased code (``SELECT Name FROM Users``) can never
be promoted into a heading. Existing monospace lines are passed
through untouched.
"""

from __future__ import annotations

import re

__all__ = ["detect_code_lines", "line_evidence"]


# ---------------------------------------------------------------------------
# Evidence rules
# ---------------------------------------------------------------------------

# Negatives first: they have precedence over every positive signal.
_URL_ONLY_RE = re.compile(r"^\s*(?:https?://|www\.)\S+\s*$")
# The list-marker family belongs to the list normalizer: a line
# beginning with one is list content, not code.
_LIST_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"[•▪‣◦∙·●○■□\-–—*+]|\(?[0-9]{1,3}[.)]|\(?[a-z][.)]|[IVXLCDM]{1,5}[.)]"
    r")\s+"
)
# Sentence-shaped prose: terminal punctuation plus enough words. Code
# lines end in ';', ',', ':', '{', ')' or nothing -- rarely '.', '!?'.
_SENTENCE_RE = re.compile(r"^[A-Za-z\"'`(].*[.!?]\s*$")

_KEYWORD_RE = re.compile(
    r"^\s*(?:"
    r"def|class|import|from|return|if|elif|else|for|while|try|except|"
    r"finally|with|raise|assert|pass|break|continue|lambda|yield|global|"
    r"nonlocal|async|await|"
    r"function|func|var|let|const|type|struct|enum|interface|package|"
    r"public|private|protected|static|void|new|delete|"
    r"export|echo|unset|local|"
    r"SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WHERE|FROM|GROUP|"
    r"ORDER|LIMIT|JOIN|HAVING|VALUES|SET|TABLE|INTO"
    r")\b"
)
_SHEBANG_RE = re.compile(r"^\s*#!")
_ASSIGNMENT_RE = re.compile(
    r"^\s*[A-Za-z_][\w.\[\]\"']*\s*(?:=[^=]|:=|<-|\+=|-=|\*=|/=|%=|&=|\|=)"
)
_CALL_RE = re.compile(r"^\s*[\w.]+\s*\(.*\)\s*[:;,]?\s*$")
_COMMENT_RE = re.compile(r"^\s*(?:#|//|--)")
_BLOCK_PUNCT_RE = re.compile(r"^\s*[{}\[\]();]\s*;?\s*$")
_OPEN_BRACE_RE = re.compile(r"[{(]\s*;?\s*$")

# Continuation lines: trailing comma or backslash, or an unbalanced
# closing fragment. These are context lines, weak on their own.
_CONTINUATION_RE = re.compile(r"[,\\]\s*$")
_DANGLING_CLOSE_RE = re.compile(r"^\s*[)\]]\s*[;,]?\s*$")

# Operator density: enough code punctuation in few words.
_OPERATOR_CHARS = re.compile(r"[=<>!+\-*/%&|^~]")

_MIN_WORDS_FOR_SENTENCE = 5
_MAX_WORDS_FOR_DENSITY = 6
_MIN_DENSITY_OPS = 2


def line_evidence(raw_text: str) -> str:
    """Classify one line's evidence: strong | weak | negative | none.

    Negative signals are checked first -- they win over any positive
    pattern, because a URL, a list item or a sentence mentioning
    ``convert(path)`` must never *become* code by accident.
    """
    text = raw_text.strip()
    if not text:
        return "none"

    if _URL_ONLY_RE.match(text):
        return "negative"
    if _LIST_MARKER_RE.match(text):
        return "negative"
    words = text.split()
    if (
        len(words) >= _MIN_WORDS_FOR_SENTENCE
        and _SENTENCE_RE.match(text)
        and not _COMMENT_RE.match(text)
    ):
        return "negative"

    if _CONTINUATION_RE.search(text) or _DANGLING_CLOSE_RE.match(text):
        return "weak"

    if (
        _KEYWORD_RE.match(text)
        or _SHEBANG_RE.match(text)
        or _ASSIGNMENT_RE.match(text)
        or _CALL_RE.match(text)
        or _COMMENT_RE.match(text)
        or _BLOCK_PUNCT_RE.match(text)
        or _OPEN_BRACE_RE.search(text)
    ):
        return "strong"

    if (
        len(words) <= _MAX_WORDS_FOR_DENSITY
        and len(_OPERATOR_CHARS.findall(text)) >= _MIN_DENSITY_OPS
    ):
        return "weak"

    return "none"


# ---------------------------------------------------------------------------
# Run detection (single pass, bounded lookahead)
# ---------------------------------------------------------------------------

# Label lines strengthen a candidate run but never establish one.
_LABEL_RE = re.compile(
    r"^[Ee]xample|^[Ll]isting|^[Cc]ode|^[Ss]ample|^[Ii]mplementation|"
    r"^[Ss]nippet|^[Oo]utput|^[Ss]ource"
)

_PITCH_HIGH = 1.7    # of the profile line height: prose spacing breaks
_PITCH_LOW = -0.5    # of the line height: baseline overlap tolerated
_X_WINDOW = 10.0     # max indent steps (char widths) inside one run
_SIZE_TOLERANCE = 0.6

_STRONG_FOR_RUN = 2          # consecutive strong lines qualify a run
_COMBINED_MIN = 3            # weaker evidence needs at least three lines
_COMBINED_STRONG = 1         # ...of which at least one must be strong
_LABEL_WINDOW = 2.5          # line heights a label may sit above the run


def _pitch_ok(prev, line, lh: float) -> bool:
    gap = line.bbox[1] - prev.bbox[3]
    return lh * _PITCH_LOW < gap < lh * _PITCH_HIGH


def _x_ok(base_x: float, line, char_w: float) -> bool:
    span = line.bbox[0] - base_x
    return -2.0 <= span <= _X_WINDOW * max(char_w, 1.0)


def _label_boosts(lines, run_start: int, lh: float) -> bool:
    """A nearby preceding label line strengthens the candidate."""
    if run_start == 0:
        return False
    label = lines[run_start - 1]
    if label.tag != "p":
        return False
    if not _LABEL_RE.match(label.raw_text.strip()):
        return False
    dist = lines[run_start].bbox[1] - label.bbox[3]
    return -lh < dist < lh * _LABEL_WINDOW


def detect_code_lines(lines: list, profile) -> list:
    """Re-tag proportional-font code runs as ``pre``, in place.

    One pass with bounded lookahead. A run starts only at a strong
    line and extends through geometry-compatible strong and weak
    lines; sentence-shaped prose and list markers always end a run
    (they are never absorbed); a URL-only line may *continue* an
    already-qualified run -- a string constant can legitimately live
    inside a listing -- but never starts one. Existing ``pre`` lines
    (the monospace path) pass through untouched.
    """
    lh = profile.line_height or (profile.body_size * 1.2)
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if line.tag != "p" or line.monospace:
            i += 1
            continue
        if line_evidence(line.raw_text) != "strong":
            i += 1
            continue

        base_x = line.bbox[0]
        char_w = line.char_width or (line.size * 0.6)
        members: list[int] = [i]
        pending: list[int] = []  # URL continuations awaiting more code
        strong = 1
        weak = 0
        j = i + 1
        while j < n:
            nxt = lines[j]
            if nxt.tag != "p" or nxt.monospace:
                break
            if not _pitch_ok(lines[j - 1], nxt, lh):
                break
            if not _x_ok(base_x, nxt, char_w):
                break
            if abs(nxt.size - line.size) > _SIZE_TOLERANCE:
                break
            established = strong >= _STRONG_FOR_RUN or (
                strong + weak >= _COMBINED_MIN
                and strong >= _COMBINED_STRONG
            )
            ev = line_evidence(nxt.raw_text)
            if ev == "negative":
                # A URL may live inside an established block as a string
                # constant, but only tentatively: if code does not
                # resume after it, it was prose following the listing
                # and is dropped. Other negatives always end the run.
                if (
                    established
                    and _URL_ONLY_RE.match(nxt.raw_text.strip())
                ):
                    pending.append(j)
                    j += 1
                    continue
                break
            if ev == "strong":
                members.extend(pending)
                pending.clear()
                members.append(j)
                strong += 1
            elif ev == "weak":
                # weak lines carry continuation syntax (trailing comma,
                # dangling close); they join unconditionally and count
                # toward the combined-evidence rule
                members.extend(pending)
                pending.clear()
                members.append(j)
                weak += 1
            else:  # "none": no code shape; ends the run
                break
            j += 1

        label_boost = _label_boosts(lines, i, lh)
        qualified = (
            strong >= _STRONG_FOR_RUN
            or (strong + weak >= _COMBINED_MIN and strong >= _COMBINED_STRONG)
            or (label_boost and strong >= 1 and strong + weak >= 2)
        )
        if qualified:
            for idx in members:
                lines[idx].tag = "pre"
            i = j
        else:
            i += 1
    return lines
