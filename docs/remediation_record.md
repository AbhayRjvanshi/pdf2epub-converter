# Post-Conversion Remediation Record

## Validation baseline before Fix 9 (2026-10-09, commit `a3cd742`)

Independently remeasured before starting non-monospace code detection
(Fix 9). Historical reference values were **remeasured, not assumed**;
every value matched, so this run supersedes nothing — it confirms the
existing baseline. Working tree was clean at `a3cd742` on `main`; the
source PDF hash matched `stage0_baseline.md`
(`369B95FE…AA9638D`).

```text
suite (venv, .venv\Scripts\python.exe -m pytest):
  637 passed, 14 skipped, 0 failed, 651 collected (cross-check), exit 0
  (14 skips = the designed gates: live provider, distribution, ace, slow)

offline regression (established procedure, docs/stage0_baseline.md):
  pdf2epub convert Artificial_Intelligence_Projects.pdf
            -o baseline_fix9_pre.epub --provider none
  exit 0, 17.3 s, no live provider, no credentials involved

measured against the fresh artifact (project checker + container read):
  chapters 1 · headings 17 · nav 17, unresolved 0 ·
  lists 11 (stream level; 12 ol/ul open tags in the body because one
  list nests a ul) · list items 50 · links 1 ·
  images 1, alt 1 · empty paragraphs 0 ·
  internal_structure_check: no findings

epubcheck 5.1.0 (npm wrapper -> java -jar epubcheck-5.1.0):
  exit 0 — 0 fatals / 0 errors / 0 warnings / 0 infos

URL regression: 'netflix-shows' present, 'netflixshows' absent
```

Baseline artifacts of this run (kept, not committed):
`%TEMP%\opencode\baseline_fix9_pre.epub` and the accompanying logs.

---

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

## Post-remediation fix: table builder return contract (2026-10-09)

**Failure class:** *Overlapping prose baselines produce table evidence
without valid grid rows.*

A 32-page SegoePrint children's book crashed Tier 1 at page 2 with
`TypeError: cannot unpack non-iterable NoneType object`: its curved
baselines (20pt text, 26pt advance) overlap by ~9pt, so every
consecutive pair registers as table-region evidence — but at 0.26
band overlap no pair clears the 0.3 same-row threshold, leaving zero
provable grid rows. One branch of `build_table_html` — the
`not multi_rows` early return — had been left as bare `return None`
when the function migrated to the `(markup, strays)` tuple contract,
and both seams (`extract_tables`, the digest fallback) unpack it.

The regression fixture also exposed a sibling defect in the same
gate region: a chain of *same-x* overlapping lines (overlap fraction
above the row threshold) clustered into a single "row" and fabricated
a table out of stacked prose. Cells are x-disjoint by definition; the
builder now refuses such rows outright.

Fixes (both minimal, no threshold or routing changes):

- `build_table_html`: the no-grid branch returns
  `None, [every candidate line]`; every return path is now a two-item
  tuple (machine-audited, zero bare branches).
- `build_table_html`: rows whose members overlap horizontally are
  prose, never a grid — the x-disjointness invariant.

Regression coverage: builder unit tests for both branches, a Tier-1
`extract_tables` seam test in the exact crash geometry, a digest
fallback seam test for the same geometry, and the
`overlapping_prose` fixture (28pt text on a 30pt advance) converting
end to end with `tables=0` and no text loss.

Verification: 631 passed / 14 skipped (5 new tests); the original
32-page conversion completes (`tier1 28/28`, `tier2 4/4` through
Kimi K3, EPUBCheck 0 errors, 6.9 MB output); the six-page offline
regression is unchanged (17 headings, 11 lists, nav 17/17, EPUBCheck
PASS). The three live NVIDIA tests were separately confirmed green in
the project venv (the SDK is installed via the `nvidia` extra; the
reported `ModuleNotFoundError` came from running the suite with the
system interpreter, which does not carry the optional provider SDKs —
the adapter's typed error identified the provider and the correct
install command, as designed).

## Post-remediation fixes: digest ordering and URL hyphens (2026-10-09)

Two approximations from the former list were closed, each with its
dedicated regression case written first:

**Digest two-column detection now requires side-by-side evidence.** A
wide x-spread alone also describes a *centered* single-column page,
where a centered heading right of the naive midpoint sorted after the
whole phantom "right column". `_detect_two_column` now declares
columns only when at least two rows of y-overlapping, x-disjoint
residents actually live on the page; genuine two-column reading order
is pinned by test and unchanged.

**A URL wrapped at its own hyphen keeps the hyphen.** The former
approximation note ("links its first fragment") was mis-diagnosed: on
the six-page reference document the URL merged whole, but the
soft-hyphen heuristic stripped the URL's own hyphen at all three join
sites (Tier-1 paragraph merge, digest fallback, cross-page weld),
silently rewriting 'netflix-shows' to 'netflixshows' — a
complete-looking link to a nonexistent page. `ends_in_url_token` now
keeps URL hyphens and joins the fragments directly; the reference
document now emits the correct href with every other metric
unchanged. Regression coverage: unit tests at each join site plus the
`hyphen_url` fixture end to end.

## Known approximations (deliberate)

- A URL wrapped mid-word *without* a hyphen still receives a space at
  the join: whether the continuation extends the URL or begins a new
  word is not decidable from the extracted text alone (the hyphenated
  half of this class is fixed above).
- Letter/roman enumerators render as unordered lists in v1.
