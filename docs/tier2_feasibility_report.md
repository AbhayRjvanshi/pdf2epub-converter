# Tier 2 Annotation Collection Feasibility — Diagnostic Report

Date: 2026-10-15
Commit: `5cab22c` on `quality-baseline`
Investigation: read-only diagnostic; no production code changed.

---

## Purpose

Determine whether collecting annotations from Tier 2 pages can recover
links, and whether the resulting annotations can be mapped to actual
output elements.

## Method

1. Reconciled the 490-record failure ledger (Task 1)
2. Traced all 319 LinuxNotes collection-failure annotations to their
   source pages and routing targets (Task 2)
3. Inspected the routing decisions, layout digests, and text content
   of the top failure pages

## Task 1 — Ledger reconciliation

| Check | Result |
|---|---|
| Total records | 490 ✓ |
| Linked (no failure stage) | 25 |
| Failed (one primary stage each) | 465 ✓ |
| collection=322 + dest=113 + geom=21 + clip=9 | = 465 ✓ |
| Categories mutually exclusive | YES (each record has exactly one stage) ✓ |
| arch_ref in ledger | 0 records — LINK_NAMED (kind=4) not captured, separate gap ✓ |
| 322 + 113 + 30 overlap | NO — the 30 arch_ref LINK_NAMED cases are not in the 490 records at all |

## Task 2 — Tier 2 feasibility findings

### The dominant failure is concentrated on table-of-contents pages

| Page | Failures | Routing target | Content |
|---|---|---|---|
| page 1 | 92 | TIER2_VISION_OCR | PDF table of contents |
| page 2 | 98 | TIER2_VISION_OCR | PDF table of contents |
| page 62 | 53 | TIER2_VISION_OCR | PDF table of contents |
| **Subtotal** | **243 (75.5%)** | | |

These three pages contain the PDF's table of contents — a two-column
layout with dot leaders (vector graphics) that triggers
`columnar_cooccurrence:-20, vector_density:-30` and routes to Tier 2
vision. In offline mode, these pages are embedded as full-page raster
images. **There are no text elements in the output. Annotations cannot
be mapped.**

### The remaining failures are on digest-routed pages

| Category | Pages | Failures | Routing target | Text in output? |
|---|---|---|---|---|
| TOC pages | 1, 2, 62 | 243 | VISION_OCR | **No** (raster image) |
| Non-TOC digest pages | 23 pages | 73 | LLM_DIGEST | **Yes** (digest fallback produces XHTML with text) |
| Non-TOC vision page | 47 | 3 | VISION_OCR | **No** (raster image) |
| **Total** | | **319** | | |

### Can digest-routed Tier 2 annotations be mapped?

**Yes.** The digest-routed pages route to `_digest_fallback` (offline),
which produces XHTML from the layout digest's line geometry. The driver
parses this XHTML via `parse_xhtml_to_stream_elements`, creating
StreamElements with:
- `page_num` set to the correct page index
- `bbox` derived from the layout digest's original text positions
- `content` containing the text

The existing link mapper can find candidate elements for these pages
because:
1. The elements have the correct `page_num`
2. The bboxes are in the PDF coordinate space (from the layout digest)
3. The text content is preserved

The annotation rectangles from the PDF should overlap with these
digest-derived element bboxes, enabling the existing geometry matching
to work.

## Feasibility assessment

| Category | Count | Feasible? | Reason |
|---|---|---|---|
| Digest-routed Tier 2 (23 pages) | 73 | **YES** | Text elements exist with correct page_num and geometry; mapper can find candidates |
| Vision-routed Tier 2 (TOC pages) | 243 | **NO** (offline) | Pages are raster images; no text elements to attach links |
| Vision-routed Tier 2 (page 47) | 3 | **NO** (offline) | Same — raster image |
| **Total** | **319** | | |

**Expected recovery from Tier 2 collection fix: 73 of 319 annotations (23%).**

The 246 vision-routed failures (TOC pages + page 47) are unrecoverable
without a routing change. They are a separate workstream: the router
currently sends table-of-contents pages to vision because of their
columnar layout and vector-density dot leaders, even though they contain
plain text. A router refinement (keeping TOC-shaped pages on Tier 1)
would recover both the text and the annotations — but that is a routing
policy change, not a link-extraction change.

## Remediation recommendation

### Smallest validated change: collect annotations from all pages

**Change**: In `driver.py`, extend annotation collection from
`tier1_indices` to all page indices. The link mapper's existing
candidate-finding logic naturally handles the case where no elements
exist (counts as `dropped_no_element` or `dropped_image`).

**Expected impact**: up to 73 additional annotations examined; the
mapper will reject the 246 vision-routed ones (no candidate elements).

**Risk**: Low — annotation collection is additive and does not change
any extraction behavior. Vision-bypassed pages produce only IMAGE
elements, which the mapper already skips.

**Tests needed**:
- A Tier 2 digest page with a URI annotation and corresponding text
- A Tier 2 vision page with annotations (should be silently dropped)
- A Tier 1 regression case

### Not recommended in this iteration

- **Router change for TOC pages**: a separate workstream; the routing
  policy affects all content extraction, not just links
- **Character-level geometry**: the ledger found 0 text-matching failures;
  this addresses a non-existent bottleneck
- **LINK_NAMED support**: separate, narrow fix (30 arch_ref annotations);
  address after the Tier 2 collection change is verified
