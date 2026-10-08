"""Heading structural roles: TITLE / MAJOR / MINOR / LEAF.

The size ladder and the structural promotion pass decide *what is a
heading*. This module decides *what the heading means for packaging*
(remediation plan, Fix 2 + Fix 7):

    depth 0  TITLE   the document's name (dc:title candidate, never a chapter)
    depth 1  MAJOR   an EPUB reading unit -> chapter boundary
    depth 2  MINOR   a section inside a chapter -> navigation entry
    depth 3+ LEAF    an in-chapter heading -> navigation anchor

Two evidence regimes, because two kinds of headings exist:

* Ladder evidence (h1/h2 from font size) is strong: the shallowest
  ladder level defines MAJOR directly, exactly like the chapters of a
  real book.
* Structural evidence (body-size h4s from the promotion pass) carries no
  size information, so depth comes from *content mass*: a heading with
  none of its own content is a container label; containers chain into a
  tree, and every content-bearing heading is a leaf attached to the
  nearest preceding container. A page break between containers means
  "sibling, not child" -- not because pages are semantic, but because a
  section that opens a fresh page cannot be nested inside one that
  closed the previous page.

Uncertainty always resolves toward fewer chapters (remediation Fix 2:
no clearly identifiable major sections means one XHTML file with full
navigation anchors).
"""

from __future__ import annotations

from dataclasses import dataclass

from .tier1_classifier import ElementType, StreamElement

TITLE, MAJOR, MINOR, LEAF = 0, 1, 2, 3

__all__ = [
    "HeadingRole",
    "infer_heading_roles",
    "infer_heading_depths",
    "TITLE",
    "MAJOR",
    "MINOR",
    "LEAF",
]


@dataclass(frozen=True)
class HeadingRole:
    index: int  # position in the stream
    depth: int  # 0 = title, 1 = major, 2 = minor, >= 3 = leaf

    @property
    def kind(self) -> str:
        return ("title", "major", "minor", "leaf", "leaf")[min(self.depth, 4)]


def _own_content_counts(stream: list[StreamElement],
                        heading_indices: list[int]) -> list[int]:
    """Non-heading elements between each heading and the next."""
    counts = []
    for pos, i in enumerate(heading_indices):
        end = heading_indices[pos + 1] if pos + 1 < len(heading_indices) else len(stream)
        counts.append(end - (i + 1))
    return counts


def _has_content_before(stream: list[StreamElement], first_heading: int) -> bool:
    # Furniture-scale text (running headers, page numbers, captions) is
    # not document content: it must not cost a heading its title role.
    return any(
        stream[j].element_type
        not in (ElementType.HEADING, ElementType.SMALL_TEXT)
        for j in range(first_heading)
    )


def infer_heading_roles(stream: list[StreamElement]) -> list[HeadingRole]:
    """One role per heading, in stream order."""
    heading_indices = [
        i for i, e in enumerate(stream)
        if e.element_type is ElementType.HEADING and e.level
    ]
    if not heading_indices:
        return []

    own = _own_content_counts(stream, heading_indices)
    levels = {stream[i].level for i in heading_indices}
    roles: list[HeadingRole] = []

    ladder_major = min((l for l in levels if l <= 2), default=None)
    if ladder_major is not None:
        # Strong regime: size evidence decided the level ladder; the
        # shallowest h1/h2 is the chapter level of a real book.
        for pos, i in enumerate(heading_indices):
            depth = stream[i].level - ladder_major + 1
            if (
                pos == 0
                and depth == 1
                and not _has_content_before(stream, i)
                and own[pos] == 0
            ):
                depth = TITLE  # a pure opening label names the document
            roles.append(HeadingRole(i, depth))
        return roles

    # Structural regime: no h1/h2 anywhere, only minor levels (3/4).
    # Content mass is the only honest depth evidence.
    prev_container_depth: int | None = None
    for pos, i in enumerate(heading_indices):
        is_container = own[pos] == 0
        if pos == 0 and not _has_content_before(stream, i):
            depth = TITLE if is_container else 1
            if is_container:
                prev_container_depth = depth
            roles.append(HeadingRole(i, depth))
            continue
        if is_container:
            if prev_container_depth is None:
                depth = 1
            elif pos and own[pos - 1] == 0 and not _page_break_before(
                stream, heading_indices, pos
            ):
                depth = prev_container_depth + 1  # label directly under a label
            else:
                depth = prev_container_depth  # sibling container
            prev_container_depth = depth
        else:
            # A leaf never opens a chapter: without a container to nest
            # under it stays a minor section (fewer chapters, never more).
            depth = (prev_container_depth + 1) if prev_container_depth is not None else MINOR
        roles.append(HeadingRole(i, depth))
    return roles


def _page_break_before(stream: list[StreamElement],
                       heading_indices: list[int], pos: int) -> bool:
    here = stream[heading_indices[pos]]
    prev = stream[heading_indices[pos - 1]]
    return here.page_num > prev.page_num


def infer_heading_depths(stream: list[StreamElement]) -> dict[int, int]:
    """Stream index -> depth for headings only (packaging convenience)."""
    return {r.index: r.depth for r in infer_heading_roles(stream)}
