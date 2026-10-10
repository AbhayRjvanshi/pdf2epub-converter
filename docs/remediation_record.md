# Post-Conversion Remediation Record

## Program closure — disposition of all 20 fixes (2026-10-10, `92f76f7`)

This section is the authoritative program summary. The chronological
entries below are the historical record and are unchanged. Commit
hashes were verified against the repository at closure time.

**Implemented and verified** — supported by the cited commits and the
closing verification (674 passed / 14 skipped / 688 collected, exit 0;
six-page offline baseline re-measured with one by-design metric change
— `code 0 → 1`, a true positive on page 5; EPUBCheck 5.1.0:
0 fatals / 0 errors / 0 warnings on both the reference and fixture
EPUBs).

**Satisfied by existing architecture** — the requirement was already
true; tests pin it rather than implement it.

**Deferred by explicit decision** — not implemented; do not read the
presence of a row here as capability.

| Fix | Disposition | Evidence | Remaining limitation |
|---|---|---|---|
| 1. Canonical representation | Satisfied by architecture — `StreamElement` is the contract; extended, never replaced | `attrs` (856992c), `char_width` (8a877f2) | the plan's parallel `SemanticDocument` tree deliberately not built |
| 2. Headings ≠ chapters | Implemented | `7e98b2d` (heading_roles, majors-only split) | — |
| 3. No page breaks from PDF pages | Satisfied by architecture | zero `page-break` rules, pinned by the CSS audit test (2ebc68a) | — |
| 4. Semantic normalizer stage | Implemented | `856992c` | — |
| 5. URL linkification | Implemented | `856992c`; hyphen preservation `a3cd742` | mid-word URL wrap without a hyphen stays ambiguous (documented) |
| 6. Semantic lists | Implemented | `856992c` | letter/roman enumerators render unordered (v1) |
| 7. Heading hierarchy | Implemented role-based — TITLE/MAJOR/MINOR/LEAF inference replaced level-jump normalization | `7e98b2d` + `26ae478` | flat structural h4 runs stay flat by design |
| 8. False heading prevention | Implemented | `26ae478` (multi-signal gates), `85ea3a3` (code tokens), `39e792e` (overlapping-prose contract) | — |
| 9. Code blocks (non-monospace) | Implemented, block-level | `8a877f2` + `92f76f7` | inline non-mono `<code>` deferred; digest/vision pages model-owned |
| 10. Table reconstruction | Implemented, both deterministic seams | `a605140` + `39e792e` | aligned pairs = prose columns (never fabricated); merged cells approximated by colspan |
| 11. Navigation as derived artifact | Satisfied, then strengthened | every heading an anchor (`7e98b2d`) | — |
| 12. Single-pass escaping | Implemented | `85ea3a3` + `7f9098e` | — |
| 13. Empty blocks | Implemented | `4f213a2` | — |
| 14. Explicit chapter sizing policy | Implemented | majors-only split + no-mass merge (`7e98b2d`) | minor-heading documents ship as one long chapter (documented trade) |
| 15. Reflowable CSS | Implemented | `2ebc68a` | `.tbl` overflow behavior varies by reader |
| 16. Structural quality validation | Implemented | `2ebc68a` + `4f213a2` + honest SKIPPED rendering (`5478aeb`) | **Ace by DAISY deferred** — npm `allow-scripts` policy blocks its postinstalls; not reported as passing |
| 17. Regression fixtures | **Partially implemented** — 12 synthetic fixtures | `make_fixtures.py` across `26ae478`, `856992c`, `2ebc68a`, `92f76f7` | synthetic fixtures prove regression protection, **not** real-world coverage — the corpus session is the follow-up |
| 18. Visual regression | **Deferred by decision** — heuristic scope only | structural checks + CSS audit test (`2ebc68a`) | no rendered-screenshot pipeline; not claimed as done |
| 19. Conversion quality metrics | Implemented | `StructureMetrics` + driver report (`2ebc68a`) | — |
| 20. Strict layer responsibilities | Satisfied and pinned | engine SDK-free test, layer-isolation tests | — |

**Program result:** the offline engine now emits the semantic
structures the original comparison showed only in the model's output
(deterministic headings, lists, links, tables, code, complete
navigation) while preserving content and passing real EPUBCheck on
every regression artifact. Deferred capabilities are exactly those
listed above — no more, no fewer.


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
Deferred by decision: 18 (visual regression — implemented as the
structural heuristics of Fix 16 plus the CSS audit test, per the
agreed "heuristic checks" scope).

## Fix 9: non-monospace code detection (2026-10-10)

**Failure class:** *proportional-font code listings classified as
prose.* Two commits, test-first throughout — 33 new tests were
confirmed failing against the pass-through before the detector landed.

- `8a877f2` — measured space advance: every classified line now
  carries its observed space-glyph advance (own line, else page
  median, else the historical 0.6×size estimate, which is exact for
  Courier), so code-indent reconstruction is honest for proportional
  fonts; the Courier regression test is unchanged and passes.
- Fix 9 detector — `engine/code_signals.py`, wired into
  `classify_page` **before** heading promotion (title-cased code such
  as `SELECT Name FROM Users` can never become a heading). One
  O(N) pass, bounded lookahead, duck-typed module. Evidence
  precedence: negatives (URL-only, list markers, sentence-shaped
  prose) checked first; strong signals (keyword statements,
  assignments, call shapes, comments, block punctuation) start runs;
  weak continuations (trailing comma, dangling close, operator
  density) join them. Two strong aligned lines qualify; three-plus
  combined with at least one strong qualify; a nearby label
  strengthens but never establishes a block alone; URL lines join an
  established run only tentatively (folded when code resumes, dropped
  at run end) — a trailing URL after a listing is prose.

**Regression coverage** (`tests/engine/test_code_signals.py` +
`proportional_code` fixture): the labeled Python listing with two
indent levels and HTML-sensitive string content, a short two-line
listing, and the label-free SQL run all classify as code through the
real Tier-1 flow and render as exactly three `<pre><code>` blocks with
faithful relative indentation (4/8 spaces, verified in the parsed XML,
not just stored metadata); the prose mention, URL line and numbered
list stay outside every block; the ordered list and hyperlink survive
in the packaged EPUB; the monospace Courier fixture is untouched.

**Verification:** 674 passed / 14 skipped / 0 failed, 688 collected
(exit 0). Fixture EPUB: `code=3`, EPUBCheck 5.1.0 exit 0 —
0 fatals / 0 errors / 0 warnings / 0 infos.

**Six-page baseline: one metric changed, by design.** `code 0 → 1`:
page 5 of the reference document contains a genuine scikit-learn
listing (`TfidfVectorizer(...)`, `max_features=50000,
sublinear_tf=True)`, `MultinomialNB(alpha=0.5)`) that every prior
stage flattened into prose — a true positive, evidenced by inspection.
All other metrics are unchanged (chapters 1, headings 17, nav 17/0,
lists 11, items 50, links 1, images 1/alt, empty paragraphs 0,
EPUBCheck 0 errors). The frozen Stage-0 record is untouched; the
pre-Fix-9 baseline above remains the historical reference.

**Known limitations:** digest/vision pages remain outside this
deterministic enhancement (the model path owns them); inline
non-monospace `<code>` remains deferred; reconstruction from geometry
cannot recover typed space counts exactly — the contract is faithful
relative indentation, with exact counts asserted only where the
fixture geometry makes them unambiguous.

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
