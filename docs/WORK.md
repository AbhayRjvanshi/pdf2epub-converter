# WORK.md — Complete Project Session Record

Date compiled: 2026-10-15
Branch at compile time: `quality-baseline` @ `eeecdbd`
Main branch HEAD: `95aabbb`

---

## Section 1 — All Decisions, Plans, Phases, and Executions

This section compiles every instruction, decision, plan, phase, and execution
issued by the project owner during this session, in chronological order.

### Phase A — Pre-Session (Prior to This Conversation)

The project had already completed:
- Post-conversion remediation program (20 fixes, commit `92f76f7`)
- Kimi K3 live-provider conversion record
- Stage-0 frozen baseline (six-page AI Projects reference PDF)
- Real-world corpus sessions (3 sessions, 14 documents, all EPUBCheck-clean)
- JPX transcode fix, furniture stripping, lxml seam escaping, URL linkification fixes

### Phase B — Round 1: Image Fidelity (Commit `e6614c5`)

**What was instructed:**
- Fix image soft masks treated as standalone images
- Fix composite illustrations split into fragments
- Fix transparency lost during compositing
- Fix false headings from all-bold SegoePrint typography
- Fix paragraph shattering (one-line-per-block)
- Eliminate `<strong>` wrapping of all-bold narrative text

**What was executed:**
- `/SMask` compositing in `_composite_with_mask` (5 masked illustrations recovered)
- Renderer-synthesized mask rasters dropped with corroborating evidence
- Solid transparency-group backplates dropped
- Duplicate placements deduplicated on bbox + content hash
- `bold_is_structural` heading demotion with `<strong>` separation
- Cross-block paragraph merging (`_continues_across_blocks`)
- 22 new tests; suite 706/20/0 offline; Flower Garden integration tests created

**Reason:** The audit identified six confirmed P0 defects from the Flower Garden conversion. All were fixed with failing-first tests and real-book verification.

### Phase C — Round 2: Publication Metadata and Accessibility (Commit `8392239`)

**What was instructed:**
- Derive title, author, language from evidence (not hardcoded defaults)
- Add cover-image designation
- Make alt-text honesty explicit (caption-derived vs location-only stubs)
- Remove unsupported WCAG-AA conformance claim
- Add `xml:lang` on OPF package element
- Improve doctor four-state diagnostics
- Add `--language` CLI flag

**What was executed:**
- Title chain: explicit → docinfo → first-page heading → filename evidence
- Author chain: explicit → docinfo → opening-pages byline (typographically guarded)
- Language policy: BCP-47 validated, catalog `/Lang` → `und` fallback
- Cover: evidence-gated page-0 full-bleed designation
- Alt-text split: caption-derived vs location-only; `alternativeText` gated
- ConformsTo removed entirely
- `xml:lang` on `<package>` via post-write OPF patch
- `--language` CLI flag threaded through `ConversionRequest`
- Doctor: env-var presence, provider selection, credential validation, model smoke check
- 33 new tests; suite 740/19/0

**Reason:** The audit confirmed these as P1 workstreams. The user approved four policy decisions via a structured question: six P1 items, honest stub + summary, remove the claim, offline-only verification.

### Phase D — README Documentation Fix (Commit `aae3e00`)

**What was instructed:**
- Update README to reflect Round 2 accessibility behavior (remove stale WCAG-AA claim)
- Regenerate package metadata (PKG-INFO)

**What was executed:**
- README accessibility section rewritten
- Stale egg-info removed locally (gitignored, regenerates from pyproject)

**Reason:** The user's ZIP audit identified this as a P2 documentation-consistency finding.

### Phase E — Round 3: Image Efficiency and Quality Instrumentation

#### E.1 — M0a: CI Workflow Fix (Commits `dee9e43`, `c6ecb21`, `d1f7415`, `870a449`)

**What was instructed:**
- Fix the CI workflow (env context invalid in job names)
- Fix the macOS memory-budget test failure
- Correct the memory measurement design (unit bug: Darwin bytes vs Linux KiB)
- Replace peak-delta with fresh-subprocess measurement
- Tighten the budget once from measurement evidence

**What was executed:**
- Workflow job name hardcoded (env context not available in job names)
- Platform-aware memory budget (initially 400/600 MB)
- Discovered Darwin/Linux ru_maxrss unit difference → replaced with `tests/memprobe.py` fresh-subprocess approach
- Budget tightened to 200 MiB from measured 58.9 MiB peak
- CI runs #1–#7 verified (runs #3 onward all 14/14 green)

**Reason:** CI had never run before this session. The user required a verified green baseline before any Round 3 work.

#### E.2 — M0b: Image Inventory (Commit `5dd3135`)

**What was instructed:**
- Build an xref-accurate image inventory with size attribution
- Freeze baselines before any encoding changes
- Traceable attribution via xref + bbox, not dimensions alone

**What was executed:**
- `scripts/image_inventory.py` (committed, reusable measurement tool)
- `docs/round3_image_inventory.md` (attribution report)
- Four baselines frozen (Flower Garden, AI Projects, C1 scan, Hands-On)
- Key findings: Flower Garden +3.6 MB is entirely mask composites; C1 5.8× raster inflation; Hands-On 13.5× JPX transcode inflation

**Reason:** The user required measurement before any encoding policy change.

#### E.3 — M3a: Page-Raster Optimization (Commit `ba935e9`)

**What was instructed:**
- Use JPEG q90 for eligible opaque scanned-page rasters
- Compare q85 vs q90 on representative C1 pages
- Keep PNG fallback for alpha-bearing rasters and encoder failures
- Confirm dimensions remain unchanged
- Validate with EPUBCheck and structural checks

**What was executed:**
- Measured eligibility (encode both, keep smaller — after a JPEG-only draft regressed the reference book)
- C1: 89,568,341 → 33,122,997 bytes (−63.0%); EPUB −66.4%
- q90 stands (q85's 13.9% extra not material against max diff 16-17/255)
- 5 failing-first tests; 743/21/0; EPUBCheck 0 errors; Ace 0/0/0/0

**Reason:** The user approved JPEG q90 with C1 validation. The measured-eligibility correction was made when a JPEG-only version regressed the born-digital reference book.

#### E.4 — M3b: Embedded-Image Investigation

**What was instructed (multi-phase):**
- Phase 1: Screen contact sheets, select candidates for comparison
- Phase 2: Visual review of all 147 images (Gate 2)
- Phase 3: Reconcile measurements and projections
- Phase 4: Compare Rules A/B/C against the 147-verdict ground truth
- Phase 5: Pin policy (lossless by default)
- Phase 6: Write failing-first policy enforcement tests
- Phase 7: Implementation decision (evidence-based: no encoder needed)

**What was executed:**
- OCR pre-screen (RapidOCR: 111/147 text-positive)
- 147 images individually reviewed with verdicts (21 JPEG-ELIGIBLE, 126 LOSSLESS, 0 PENDING)
- Rules A/B/C compared: all three rejected (0-109 false approvals each)
- Lossless-by-default policy pinned (M3B_POLICY.md)
- 13 policy enforcement tests (all pass against unchanged code)
- No production encoder needed — the architecture already enforces the policy
- Realized M3b saving: 0% (the 47.86 MB stays as lossless PNG)
- All evidence merged into main via `f22369b` and consolidated at `95aabbb`

**Reason:** The user directed each phase with specific conditions. The investigation concluded that the four measured features (micro, flat, crisp, colors) cannot reliably separate photographs from text-bearing diagrams. The user approved lossless-by-default and the 13 test regression guards.

#### E.5 — Round 3 Record Consolidation (Commit `95aabbb`)

**What was instructed:**
- Update docs/round3_record.md to reflect completed M3b (remove stale "in progress")
- Add Phase 7 closure, final CI evidence, completion summary
- Run the Phase 9 consistency audit

**What was executed:**
- M3b section replaced with final findings
- 9/9 consistency audit checks passed
- CI run #30: 14/14 green

**Reason:** The user identified that the record still had stale M3b language from before the merge.

### Phase F — Conversion Quality Baseline and Hyperlink Remediation

#### F.1 — Quality Baseline and Defect Register (Commit `c277241`)

**What was instructed:**
- Verify the baseline (commit, clean tree, test suite)
- Audit the conversion paths for each quality dimension
- Build a representative test corpus
- Run baseline conversions and record defects

**What was executed:**
- Architecture audit: text, reading order, structure, tables, notes (complete gap), images, links (complete gap)
- 4 documents converted (LinuxNotes, AI_Projects, arch_ref, Flower Garden)
- Confirmed defects: LINK-001 (91 missing external URIs), LINK-002 (238 missing internal links), NOTE-001 (32 pages of disconnected footnote text)

**Reason:** The user approved this as the next workstream after Round 3, focusing on conversion quality rather than additional image compression.

#### F.2 — Whole-Element Hyperlink Extraction (Commit `d442818`)

**What was instructed:**
- Extract PDF link annotations via `page.get_links()`
- Map annotations to StreamElements by bbox coverage
- Apply links at render time (not during extraction)
- Guard with coverage threshold
- Whitelist URI schemes (http/https/mailto)
- Prevent duplicate links (annotation + text URL → single anchor)
- Handle internal GOTO links with chapter resolution
- Drop unsupported schemes and malformed annotations

**What was executed:**
- `extract_page_links()` and `apply_link_annotations()` in `tier1_classifier.py`
- `link_uri` and `link_target_page` fields on StreamElement
- `render()` applies link wrapper with duplicate prevention
- Internal GOTO resolution via chapter mapping in packaging
- 6 failing-first tests; full suite 763/23/0
- Real corpus: LinuxNotes improved 4→7 URIs, 0→2 internal links (limited by coverage guard rejecting partial-element annotations)

**Reason:** The user conditionally approved with four safeguards (coverage guard, URI whitelist, chapter-level internal links, image links deferred).

#### F.3 — Sub-Span Link Mapping (Commit `c2029d8`)

**What was instructed:**
- Improve mapping precision without weakening the coverage guard
- Extract annotation text via `page.get_text("text", clip=rect)`
- Reject ambiguous matches (multiple occurrences), don't link first occurrence
- Preserve page-specific annotation metadata at extraction time
- Check for overlapping link ranges
- Apply after welding/stripping, before normalization

**What was executed:**
- `engine/link_mapper.py` created (focused helper module)
- `extract_page_links()` now captures `clip_text` and `source_page`
- Link application moved from extraction-time to post-welding
- `map_subspan_links()` in `link_mapper.py`: text matching, ambiguity rejection, overlap detection, whole-element fallback
- `mailto:` added to structural check's external-link skip list
- 6 tests pass; full suite 763/23/0
- Real corpus: LinuxNotes 10/93 URIs (was 7), 6/208 internal (was 2)

**Reason:** The user approved with two changes: reject ambiguous matches, preserve page-specific metadata. The mailto: structural check fix was needed because mailto links were being validated as broken internal references.

#### F.4 — Per-Annotation Failure Ledger (Commit `5cab22c`)

**What was instructed:**
- Trace every missing link through the complete disposition chain
- Record collection status, clip text, geometry, matching, ambiguity, resolution
- Assign one primary failure stage per annotation
- Keep failure categories distinct
- Make the diagnostic reproducible

**What was executed:**
- 490 annotations traced (485 LinuxNotes + 5 AI_Projects)
- Key finding: **collection is the dominant failure (69.2%)** — not text matching (0%)
- 322 failures from Tier 2 pages (annotations never collected)
- 113 destination-resolution failures (text matched but URI not in EPUB)
- 21 candidate-geometry failures, 9 empty clip text
- 0 text-matching failures, 0 ambiguous rejections
- `docs/link_failure_ledger.md` + `docs/link_failure_ledger.json` (490 per-annotation records)

**Reason:** The user required evidence-based diagnosis before further implementation.

#### F.5 — Tier 2 Feasibility Investigation (Commit `eeecdbd`)

**What was instructed:**
- Reconcile the ledger (verify 490 records, check category exclusivity)
- Trace representative Tier 2 annotations
- Determine whether Tier 2 output contains mappable text elements
- Decide the scope of the collection fix

**What was executed:**
- Ledger reconciled: 465 failed + 25 linked = 490; categories mutually exclusive
- 75.5% of collection failures (243/319) on TOC pages routed to vision (no text output)
- 23% (73/319) on digest-routed pages where text elements exist
- 1 vision-routed page (47) with 3 unmappable failures
- `docs/tier2_feasibility_report.md`

**Reason:** The user required validation before implementation — "collection should not imply that every annotation is eligible for linking."

---

## Section 2 — Status Tracking

### Completed ✅

| Item | Status | Evidence |
|---|---|---|
| Round 1: Image fidelity fixes | ✅ Complete | Commit `e6614c5`; 22 tests; Flower Garden integration gates |
| Round 2: Metadata derivation | ✅ Complete | Commit `8392239`; 33 tests; EPUBCheck+Ace clean |
| README documentation fix | ✅ Complete | Commit `aae3e00`; stale WCAG claim removed |
| M0a: CI workflow fix | ✅ Complete | Commits `dee9e43`→`d1f7415`; runs #3 onward 14/14 green |
| M0a: Memory gate correction | ✅ Complete | `tests/memprobe.py`; 200 MiB budget; runs #6–#7 verified |
| M0b: Image inventory | ✅ Complete | Commit `5dd3135`; `scripts/image_inventory.py`; 4 baselines frozen |
| M3a: Page-raster optimization | ✅ Complete | Commit `ba935e9`; C1 −66.4%; EPUBCheck+Ace clean |
| M3b: OCR pre-screen | ✅ Complete | RapidOCR evidence in record; 111/147 text-positive |
| M3b: 147-image visual review | ✅ Complete | All verdicts recorded; Gate 2 closed at `9708438` |
| M3b: Rule A/B/C comparison | ✅ Complete | All three rejected; `PHASE4_REPORT.md` |
| M3b: Policy pinned | ✅ Complete | `M3B_POLICY.md`; lossless by default |
| M3b: Policy enforcement tests | ✅ Complete | 13 tests; all pass; merged to main |
| M3b: Consolidation and merge | ✅ Complete | `f22369b` merge; `95aabbb` record; CI #30 14/14 |
| Quality baseline audit | ✅ Complete | Commit `c277241`; LINK-001/002/NOTE-001 quantified |
| Whole-element link extraction | ✅ Complete | Commit `d442818`; 6 tests; 763/23/0 |
| Sub-span link mapping | ✅ Complete | Commit `c2029d8`; `engine/link_mapper.py`; 763/23/0 |
| Per-annotation failure ledger | ✅ Complete | Commit `5cab22c`; 490 records; collection=69.2% dominant |
| Tier 2 feasibility investigation | ✅ Complete | Commit `eeecdbd`; 73 recoverable / 246 unrecoverable |

### Left To Do (Not Yet Started) 📋

| Item | Priority | Prerequisites | Notes |
|---|---|---|---|
| **Tier 2 annotation collection (digest-routed pages)** | High | Tier 2 feasibility ✅ | Extend collection from `tier1_indices` to all pages; expected recovery ~73 annotations; smallest safe change |
| **LINK_NAMED support (kind=4)** | Medium | None | 30 arch_ref annotations; extend kind filter; verify target semantics |
| **Destination-resolution investigation** | Medium | Failure ledger ✅ | 113 failures where text matched but URI didn't reach EPUB; needs diagnostic logging at the first failing pipeline stage |
| **Footnote/endnote support (NOTE-001)** | Medium-High | None | 32 pages of disconnected footnote text; requires marker detection, note association, and EPUB navigation semantics — a separate design phase |
| **Router refinement for TOC pages** | Low (separate workstream) | None | 243 GOTO links on vision-routed TOC pages; a routing policy change (keep TOC-shaped pages on Tier 1) would recover text AND annotations — but affects all extraction, not just links |
| **Corpus validation after Tier 2 fix** | Required after Tier 2 fix | Tier 2 collection implemented | Re-run LinuxNotes, AI_Projects, arch_ref; measure new link counts; compare against baseline |
| **Merge quality-baseline to main** | After all fixes verified | Tier 2 + LINK_NAMED + destination-resolution | Currently 5 commits ahead of main; merge only after evidence review |

### Drifted From (Started but Changed Direction) 🔄

| Item | Original Direction | What Actually Happened | Reason |
|---|---|---|---|
| M3b: Embedded-image JPEG transcoding | Planned to implement a three-outcome classifier and selectively JPEG-compress embedded images | Investigation revealed no reliable classifier exists; policy decision: lossless by default; no encoder built | The 147-image review and Rule A/B/C comparison showed the four features cannot separate photographs from text-bearing diagrams; implementing an unsafe classifier would have introduced lossy encoding of lossless-required content |
| 73.4% size-reduction projection | Expected to achieve significant EPUB size reduction on the Hands-On transcoded class | Projection withdrawn; realized M3b saving is 0% | The permissive rule (A) that produced the projection was refuted by the OCR pre-screen (111/147 text-positive); no validated automatic rule exists to select eligible images |
| Character-level geometry mapping for link text matching | Proposed as the next refinement after sub-span linking showed limited corpus coverage | The failure ledger showed 0 text-matching failures; the dominant gap is annotation collection (69.2%), not text precision | Evidence-based redirection: the text matching works correctly when annotations are collected; the bottleneck is that 322 annotations are never examined because their pages route to Tier 2 |
| Platform-aware memory budget (400 Linux / 600 macOS) | Initially implemented as a platform-specific calibration | Replaced entirely with fresh-subprocess measurement with unit normalization | The Darwin/Linux ru_maxrss unit difference (bytes vs KiB) made the platform-split budget based on an invalid interpretation; the corrected approach measures the conversion's own peak in a fresh process with normalized units |

### Abandoned (Explicitly Rejected) ❌

| Item | Status | Reason |
|---|---|---|
| WCAG-AA conformance claim | ❌ Removed in Round 2 | The tool never ran a WCAG audit; an unconditional claim would mislead readers and distributors |
| Image-targeted link annotations | ❌ Deferred in Phase F | Different markup semantics (wrapping `<figure>` in `<a>`); not tested; recorded as a known limitation |
| OCR of scanned pages | ❌ Out of scope | Tier policy: vision pages embed rasters offline; OCR is a model/feature decision, not a defect |
| q85 JPEG for scanned pages | ❌ Rejected by evidence | q85's 13.9% additional saving not material against max diff 16-17/255 vs q90's 10-11/255 |

### Known Limitations (Documented, Not Fixable in Current Scope) ⚠️

| Limitation | Disposition | Reason |
|---|---|---|
| Scanned pages are full-page rasters (no OCR) | Out of scope | Documented tier policy; requires a model |
| Vision-routed TOC pages produce no text output | Router design | 243 GOTO links lost; a router change is a separate workstream |
| 113 destination-resolution failures | Under investigation | Text matched but URI not in EPUB; needs pipeline-stage tracing |
| Aligned tables stay prose | By design | No-fabrication rule: cleanly-aligned pairs are indistinguishable from two-column prose |
| Digest-page furniture below position-evidence guard | Deferred | Cross-page text-echo needed; low value while model path owns those pages |
| `we re ready to open` (Flower Garden p.22) | Source-level defect | ToUnicode gap in the source PDF; not a conversion error |
| Image size (PNG inflation) | Deferred to Round 3 by scope agreement | M3a handles scanned-page rasters; M3b embedded images stay lossless (correctly) |

---

## Branch State Summary

| Branch | HEAD | Status | Relationship |
|---|---|---|---|
| `main` | `95aabbb` | Stable; Round 3 complete | Production branch |
| `quality-baseline` | `eeecdbd` | Active; hyperlink remediation in progress | 5 commits ahead of main |
| `review/m3b-images` | `3201282` | Merged into main at `f22369b` | Historical (M3b review) |

### Commits on `quality-baseline` (not yet on main)

| Commit | Description |
|---|---|
| `c277241` | Quality baseline defect register |
| `d442818` | Whole-element hyperlink extraction |
| `c2029d8` | Sub-span link mapping |
| `5cab22c` | Per-annotation failure ledger |
| `eeecdbd` | Tier 2 feasibility report |

All 5 commits are diagnostic and implementation work for the hyperlink
remediation. The 6 link-extraction tests and the full suite (763/23/0)
pass on this branch. Main remains untouched.

---

*This document was compiled from the complete session history, commit log, and all user instructions. It serves as the authoritative record of what was decided, what was done, what remains, and what changed direction — with the reasoning for each.*
