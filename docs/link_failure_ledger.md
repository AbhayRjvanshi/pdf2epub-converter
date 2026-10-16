# Link Failure Ledger — Per-Annotation Diagnosis

Date: 2026-10-15
Baseline commit: `c2029d8` on `quality-baseline`
Investigation: read-only diagnostic; no production code changed.

---

## Headline finding

**The dominant failure is annotation collection (69.2%), not text matching (0%).**

The text-matching precision hypothesis that motivated the sub-span linking design is not the bottleneck. The evidence shows that most missing links were never collected because their source pages route to Tier 2 (digest), and the driver only collects annotations from Tier 1 pages.

## Methodology

All PDF link annotations from three documents were traced through the complete disposition chain:
1. Collection (was the source page routed to Tier 1?)
2. Clip text (is the annotation's extracted text usable?)
3. Candidate geometry (does an element overlap the annotation rectangle?)
4. Text matching (does the clip text appear in the candidate's content?)
5. Ambiguity (does the text appear more than once?)
6. Destination resolution (does the link reach the EPUB output?)

Each annotation received exactly one `primary_failure_stage` classification.

## Results

### Aggregate

| Metric | Count |
|---|---|
| Total annotations traced | 490 |
| Successfully linked (reached EPUB) | 25 |
| Failed (primary_failure_stage assigned) | 465 |

### Primary failure stages (all documents)

| Stage | Count | Share | What it means |
|---|---|---|---|
| **collection** | **322** | **69.2%** | Annotation's source page routed to Tier 2; driver only collects from Tier 1 |
| **destination_resolution** | **113** | **24.3%** | Clip text matched an element but the URI/link did not appear in the EPUB output |
| **candidate_geometry** | **21** | **4.5%** | No non-image element on the source page overlaps the annotation rectangle |
| **clip_text** | **9** | **1.9%** | The annotation's extracted text is empty or whitespace-only |
| text_matching | 0 | 0% | The clip text was always found when it was usable and a candidate existed |
| ambiguous | 0 | 0% | No text appeared multiple times in any candidate element |

### Per-document breakdown

| Document | Total | Failed | collection | destination_resolution | candidate_geometry | clip_text |
|---|---|---|---|---|---|---|
| LinuxNotes | 485 | 461 | 319 | 113 | 20 | 9 |
| AI_Projects | 5 | 4 | 3 | 0 | 1 | 0 |
| arch_ref | 0* | 0 | — | — | — | — |

*arch_ref's 30 links are `LINK_NAMED` (kind=4), not `LINK_GOTO` (kind=1) — they are invisible to the current `extract_page_links` filter, which only handles `LINK_URI` (kind=2) and `LINK_GOTO` (kind=1). This is a separate implementation gap.

## Ranked bottlenecks (by measured impact)

| Rank | Bottleneck | Evidence | Actionability |
|---|---|---|---|
| **1** | **Tier 2 annotation collection** | 322 of 465 failures (69.2%): pages routed to Tier 2 (digest) never have annotations collected | **High** — the fix is architectural (collect annotations independently of the text-extraction route), not a text-matching refinement |
| **2** | **Destination resolution pipeline** | 113 of 465 failures (24.3%): text matching succeeded but the URI didn't appear in the EPUB output | **Medium** — needs investigation; possible pipeline bug where sub-span or whole-element links are lost during subsequent transformations |
| **3** | **LINK_NAMED support** | 30 arch_ref links use `kind=4` (named destinations), not captured by `extract_page_links` | **Medium** — PyMuPDF resolves the target page; the fix is extending the kind filter |
| **4** | Candidate geometry | 21 failures (4.5%): annotation rectangle overlaps no non-image element | **Low** — character-level geometry mapping could help, but it addresses the smallest measured category |
| **5** | Clip text | 9 failures (1.9%): annotation rectangle contains no extractable text | **Low** — likely decorative or image-only annotations |

## What the evidence does NOT support

- **Text-matching precision is NOT the bottleneck**: 0 text_matching failures. The clip text was always found in the candidate element when it was usable and geometry overlapped. Character-level geometry mapping would address a category with zero measured failures.
- **Ambiguity is NOT the bottleneck**: 0 ambiguous rejections. The multiple-occurrence rejection policy is correct but rarely triggered in this corpus.
- **The provisional >50 URI target was misdirected**: the text-matching approach could not have reached 50+ URIs because 322 annotations are never collected (their pages route to Tier 2). No amount of text-matching refinement would recover them.

## Remediation proposal (not implemented)

### Priority 1: Extend annotation collection to all pages

**Problem**: The driver collects annotations only from `tier1_indices`. Pages routed to Tier 2 (digest) — which in LinuxNotes is the majority of pages with link annotations — never have their links examined.

**Proposed fix**: Collect annotations from ALL pages, not just Tier 1 pages. The annotations are page-level metadata, independent of the text-extraction route. The driver should call `extract_page_links()` for every page, not just Tier 1 pages.

**Expected recovery**: up to 322 additional annotations across the corpus (the `collection` category).

**Risk**: Low — annotation collection is additive and does not change text extraction. The sub-span mapper already handles elements from any page via the `source_page` field.

### Priority 2: Investigate destination-resolution failures

**Problem**: 113 annotations had their clip text matched to an element but the URI did not appear in the EPUB. This suggests the sub-span wrapping or whole-element metadata application is producing links that are lost during subsequent stream transformations (welding, stripping, normalization) or during packaging.

**Proposed investigation**: Add diagnostic logging to the link mapper's output (what was applied) and the packaging stage's input (what survived) to identify where the links are dropped.

### Priority 3: Add LINK_NAMED support

**Problem**: `extract_page_links` only handles `LINK_URI` and `LINK_GOTO`. Named destinations (`LINK_NAMED`, kind=4) with resolvable target pages are dropped.

**Proposed fix**: Extend the kind filter to include `LINK_NAMED` when `link.get("page", -1) >= 0`.

**Expected recovery**: 30 arch_ref internal links.

## Reproducibility

```powershell
# diagnostic script (read-only, no production changes)
$env:NVIDIA_API_KEY = $null
.venv\Scripts\python.exe <ledger script>

# baseline conversion for link counting
.venv\Scripts\python.exe scripts\image_inventory.py <pdf> --out-dir <dir>
```

Source hashes: LinuxNotes `0dd240cc90262f45...`, AI_Projects `369b95fe20c4511b...`, arch_ref `f75ef2bdb07c9602...`.
Toolchain: PyMuPDF 1.28.2, Python 3.10 (.venv), Windows 10.
Commit: `c2029d8` on `quality-baseline`.
