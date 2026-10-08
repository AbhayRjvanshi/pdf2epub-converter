# Post-Conversion Remediation Record

Outcome record for
[post-conversion remediation plan](pdf_to_epub_post_conversion_remediation_plan.md),
executed 2026-10-09. The plan's 20 fixes were reconciled against the
codebase first: five were already satisfied (canonical representation
= `StreamElement`; no page breaks anywhere; navigation already derived
post-merge; false-heading guards from the earlier Phase K), and the
remaining work landed in four stages, one commit per boundary.

## Commits

| Commit | Stage | Contents |
|---|---|---|
| `7f9098e` | 1a — escaping | Single-pass escaping at every ownership boundary (sanitizer entity guard, plain-text fallback, dc:title path); `special_chars` fixture + escaping matrix |
| `4f213a2` | 1b — empties | Empty-block elimination at every seam (Tier-2 passthrough, regex fallback, chapter body, `<br>` runs) + structural flags |
| `7e98b2d` | 2 — chapter policy | `heading_roles` TITLE/MAJOR/MINOR/LEAF inference; chapters split at majors only; single-chapter documents keep full nav; nav lists every heading anchor |
| `856992c` | 3 — normalizer | `semantic_normalizer`: URL linkification + list reconstruction (ordered/unordered, starts, nesting, page-spanning runs, wrapped tails) |
| `2ebc68a` | 4 — validation & presentation | `StructureMetrics` + driver quality report; double-escape and nav-fragment structural checks; reflowable CSS (lists, h4–h6, thead, links) + no-page-break audit |
| (this pass) | 5 — Fix 10, tables | `build_table_html` in `heading_signals` + two seams: Tier-1 `extract_tables` (staggered grids score high and legitimately stay heuristic) and the digest fallback (every columnar layout lands there offline). Fixture: `staggered_table` |

## Six-page offline repro, end to end

Same source PDF (hash in [stage0_baseline.md](stage0_baseline.md)),
`--provider none`, new output each run:

| Metric | Stage 0 (frozen) | Kimi K3 | After Phase K/L/M | After remediation |
|---|---|---|---|---|
| headings | 0 | 6 | 17 | 17 |
| dc:title | Untitled Publication | Untitled Publication | Artificial Intelligence | Artificial Intelligence |
| chapters | 1 | 2 | 18 | **1** (page 3 is vision-preserved; majors = 1 offline, 2 with a model) |
| nav entries | 0 | 6 | 17 | 17 (chapter + every anchor) |
| semantic lists | 0 | 1 | 0 | **11** (ordered, unordered, nested) |
| list items | 1 | 7 | 1 | **50** |
| hyperlinks | 0 | 2 | 0 | 1 text URL (page-3 URLs live inside the preserved raster) |
| empty paragraphs | — | — | — | 0 |
| unresolved nav targets | — | — | — | 0 |
| EPUBCheck 5.1.0 | skipped | skipped | PASS | **PASS, 0 errors** |

The offline engine now emits the same semantic structures the live
model produced (lists, navigation, links) plus the structures the model
did not (17 deterministic headings, derived title) — at zero API cost.

## Fix-by-fix disposition

Done in this pass: 2, 4, 5, 6, 7 (role-based), 10 (deterministic grids,
both reachable seams), 12 (all three remaining hazards), 13, 14, 15, 16
(structural-quality extensions), 17 (fixtures: `special_chars`,
`nested_lists`, `staggered_table` + the Phase K set), 19.
Already satisfied before this pass: 1 (extend, not rebuild — the stream
*is* the contract), 3, 8, 11, 20.
Deferred by decision: 9 (non-monospace code detection), 18 (visual
regression — implemented as the structural heuristics of Fix 16 plus
the CSS audit test, per the agreed "heuristic checks" scope).

## Table reconstruction scope (Fix 10)

The builder reconstructs a grid only when the geometry proves it:

* **staggered cells** — side-by-side lines whose vertical bands overlap
  imperfectly (the shape real extracted tables show) are the evidence
  that separates a table from a two-column article;
* **cleanly aligned pairs return None** — they are geometrically
  indistinguishable from two-column prose, and the plan forbids
  guessing cell relationships;
* leading single lines above the grid (captions, headings) are ejected
  back to prose instead of poisoning the grid;
* wrapped cells continue their column, spanning bars get an honest
  `colspan`, a fully bold first grid row becomes `<thead>`, and
  anything ragged after those explanations keeps every line as prose.

Reached by both deterministic seams: Tier 1 (`extract_tables`) —
staggered cells fall *under* the router's columnar-overlap threshold
and legitimately stay heuristic — and the offline digest fallback
(every columnar layout routes there). The six-page document's own
table page remains vision-preserved offline by design; the
`staggered_table` fixture pins the rebuilt grid end to end
(`tables=1`, `<td>` cells, surrounding prose intact, EPUBCheck clean).

## Known approximations (deliberate)

- The digest fallback's two-column sort places short centered headings
  last (page ordering only; the affected six-page page is
  vision-routed, so the real pipeline is not impacted).
- A URL split across tight-leading wrapped lines links its first
  fragment (conservative; same-page continuation merging is out of
  remediation scope).
- Letter/roman enumerators render as unordered lists in v1.
