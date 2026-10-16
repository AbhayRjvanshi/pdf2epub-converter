# WORK.md — Complete Project Session Record

Date compiled: 2026-10-15
Branch at compile time: `quality-baseline` @ `ad08950`
Main branch HEAD: `95aabbb` (Round 3 complete)
Total commits in repository: 113 (from `a01f194` initial commit)
Commits created during this session: 71 (from `e6614c5` Round 1 through `ad08950` this record)

---

## Section 1 — All Decisions, Plans, Phases, and Executions

This section chronologically documents every instruction, decision, plan,
phase, and execution from this conversation, with full detail on what was
instructed, what was executed, specific files changed, test counts, CI
results, metrics, and the reasoning behind each action.

---

### Phase A — Pre-Session Context (Repository State Before This Conversation)

The project had already completed, across prior sessions:

| Work | Commit | Details |
|---|---|---|
| Provider layer (OpenAI/Anthropic/NVIDIA adapters) | `c85b19e`–`fd708c0` | Credential resolution, config manager, registry, catalog, typed errors |
| CLI (headless + interactive REPL) | `7dd369e`–`02f0572` | ConversionRequest, ConversionService, session, commands, doctor |
| CI workflow | `358962e` | ubuntu/macos/windows × Python 3.10–3.13, distribution tests, EPUBCheck 5.1.0 conformance job |
| Kimi K3 live conversion record | `8a75eeb` | NVIDIA provider, tier2=2/2 pages, 680.5s, EPUBCheck clean |
| Post-conversion remediation program | `68a5b39` | 20 fixes (escaping, empties, headings, links, lists, tables, code, CSS, validation, metrics) |
| Real-world corpus sessions (3) | `2940e0a`, `2762fd3`, `3947fa2`, `4bff243` | 14 documents, all EPUBCheck-clean; JPX transcode, furniture stripping, lxml seam escaping, URL linkification fixes |

Key evidence documents from prior sessions:
- `docs/stage0_baseline.md` — frozen six-page AI Projects reference
- `docs/kimi_k3_conversion_record.md` — live-provider conversion
- `docs/remediation_record.md` — 20-fix disposition
- `docs/corpus_record.md` — 3 corpus sessions, 14 documents
- `docs/pdf_to_epub_post_conversion_remediation_plan.md` — the original plan

---

### Phase B — Round 1: Image Fidelity (Commit `e6614c5`)

**What was instructed (user message):**
The user provided a comprehensive fault and defect audit of the PDF-to-EPUB
converter covering the entire pipeline (10 stages), with confirmed defects
from the Flower Garden children's book conversion, known tradeoffs, and
investigation requirements. Six confirmed P0 defects were identified:
1. Soft masks treated as standalone images (page 6: 828×335 grayscale artifact)
2. Transparency lost during compositing
3. False headings from all-bold SegoePrint typography (page 24: 10 false h4 elements)
4. Paragraph shattering (one-line-per-block, 145 fragmented paragraphs)
5. `<strong>` wrapping all-bold narrative (191 elements)
6. Composite illustrations split into fragments

**Plan mode:** The user initially placed me in Plan mode. I conducted a
read-only inspection of the Flower Garden PDF, source code, and baseline
artifacts. Key evidence gathered:
- Flower Garden PDF: SHA-256 `e91fcea3...`, 32 pages, docinfo all empty
- 27 opaque byte-identical JPEG passthroughs, 8 alpha PNGs (5 mask composites)
- The +3.6 MB growth fully attributed to the 5 mask composites (840,700 → 4,446,821 bytes)
- `SegoePrint-Bold` is 94.1% of body characters
- Root EPUB (BEFORE artifact): SHA-256 `CD0DED00...`, 39 assets, 191 strongs, 10 h4s

**What was executed:**

| Sub-fix | File(s) changed | Details |
|---|---|---|
| SMask compositing | `tier1_classifier.py` | `_composite_with_mask()` using `fitz.Pixmap(base, mask)`; on failure, opaque base kept with warning; 5 masked illustrations (pages 6, 10, 11, 29, 31) recovered with alpha |
| Renderer artifact filtering | `tier1_classifier.py` | Drop rule requiring: grayscale colorspace + no backing xref + /SMask'd image on page + bbox overlap; solid transparency-group backplates dropped (pages 31/32) |
| Duplicate placement dedup | `tier1_classifier.py` | bbox + content hash |
| Bold heading demotion | `heading_signals.py`, `tier1_classifier.py`, `tier2_llm_handler.py`, `confidence_router.py`, `driver.py` | `DocumentFontProfile.bold_char_share` (char-weighted); `bold_is_structural` (< 0.60); size ladder bold argument now receives `is_bold(...) and profile.bold_is_structural` |
| `<strong>` separation | `tier1_classifier.py`, `tier2_llm_handler.py` | Document-norm boldness emits no `<strong>`; bold spans in other fonts keep the tag |
| Cross-block paragraph merging | `tier1_classifier.py`, `tier2_llm_handler.py` | `_continues_across_blocks`: same tag, size within 0.6pt, same font, x-range overlap ≥ 50%, left edges within 2 font sizes, neither list-marked, previous not sentence-terminating, next lowercase-initial; digest fallback gained identical rule (`_cross_block_continues`) |
| Engine boundary hardening | `driver.py` | None title/author normalization prevents `<title/>` EPUB |

**Tests:** 22 new tests (12 image fidelity, 5 heading/emphasis, 3 cross-block,
2 env-gated integration skips). Files: `test_image_fidelity.py` (new),
`test_flower_garden.py` (new, env-gated on `PDF2EPUB_FLOWER_PDF`),
extensions to `test_tier1.py`, `test_heading_signals.py`, `make_fixtures.py`.

**Test suite evolution:**
- Before Round 1: 684 passed / 18 skipped (EPUBCheck hidden)
- After Round 1: 706 passed / 20 skipped (offline), 710/16 with EPUBCheck
- With EPUBCheck + Ace: 3 offline e2e tests failed (Ace epub-lang, document-title, empty-heading violations — Round 2 candidates)

**Real-book verification (Flower Garden integration test):**
- No false headings: ten page-24 fragments absent from h1–h6 and nav
- "Your Story Book!" survives as a heading
- No `<strong>` in any chapter body
- Cross-block joins present ("mom and dad. They ran" only exists when merged)
- No 828×335 mask artifact packaged; ≥5 alpha PNGs; 35 assets (was 39)
- EPUBCheck 0 errors

**Metrics (BEFORE → AFTER):**
| Metric | Before | After |
|---|---|---|
| Media assets | 39 | 35 |
| 828×335 gray mask artifacts | 1 | 0 |
| Alpha-carrying PNGs | 6 | 8 |
| h4 elements (page-24 class) | 10 | 0 |
| `<strong>`-wrapped body lines | 191 | 0 |
| Paragraph elements | 145 | 130 |
| Nav TOC entries | 12 | 2 |
| EPUB media bytes | 7.0 MB | 10.6 MB |

**Reason:** The user's comprehensive fault audit identified these as the
highest-priority confirmed defects. The investigation-first approach
(Plan-mode read-only inspection before implementation) was mandated by
the user's governing rule: "identify the first incorrect stage, prove
the failure with a fixture, fix that stage, and verify end to end."

---

### Phase C — Round 2: Publication Metadata and Accessibility (Commit `8392239`)

**What was instructed:**
The user approved six P1 workstreams with four policy decisions made via
a structured question:
1. Scope: six P1 items only (recommended)
2. Alt-text policy: honest stub + summary (recommended)
3. WCAG claim: remove entirely (user chose removal, not gating)
4. Verification: offline-only (recommended)

**What was executed:**

| Sub-fix | File(s) changed | Details |
|---|---|---|
| Title filename tier | `driver.py` | `_filename_title_candidate()`: leading uppercase word run ≥2 words, ≤120 chars, digits preserved; fires only when explicit + docinfo + first-page heading all fail |
| Author byline tier | `driver.py` | `_first_pages_byline_candidate()`: `^By\s+Name` on first 3 pages; typographically distinct (smaller than body or different font) via `_typographically_distinct()`; "Published by"/"Illustrated by" excluded by `^By` anchor |
| Language policy | `driver.py`, `packaging_and_validation.py`, `models.py`, `conversion_service.py`, `cli/headless.py` | `BCP47_RE`; `_derive_language()`: explicit → catalog `/Lang` (validated) → `und`; packaging default changed from `"en"` to `"und"`; `--language` CLI flag |
| Cover designation | `driver.py`, `packaging_and_validation.py` | `_cover_image_candidate()`: page-0, ≥90% area coverage, ≤200 chars text; `_cover_image` param; `EpubCover` item class |
| Alt-text honesty | `tier1_classifier.py`, `packaging_and_validation.py` | `ImageElement.alt_source` field ("caption"|"location"); `AccessibilityProfile.images_described/images_location_only`; `alternativeText` gated on all-caption; summary states location-only |
| Caption no-fabrication | `tier1_classifier.py` | `_harvest_alt_text()` requires `CAPTION_RE` match; non-caption lines below images rejected (found via Flower Garden's Patreon plea on page 3) |
| ConformsTo removal | `packaging_and_validation.py` | `CONFORMS_TO` constant and injection removed entirely |
| xml:lang on package | `packaging_and_validation.py` | `_set_package_xml_lang()` post-write OPF patch; `_opf_with_xml_lang()` lxml re-serialization |
| Nav title | `packaging_and_validation.py` | `epub.EpubNav(title=title)` |
| Doctor 4-state | `application/doctor.py` | Env-var presence rows per credential variable; `_append_model_request_check()` opt-in under `--verify-credentials`; separate provider selection, credential validation, model smoke check |

**Tests:** 33 new tests (14 publication-metadata, 8 packaging-a11y, 5 doctor,
1 tier1 caption, 2 packaging, 2 CLI, 1 integration gate). Files:
`test_publication_metadata.py` (new), `test_packaging.py` (extended),
`test_doctor.py` (extended), `test_tier1.py` (extended),
`test_flower_garden.py` (extended with Round 2 gates),
`test_headless.py` (extended).

**Test suite evolution:** 740 passed / 19 skipped (offline with Flower Garden env var set)

**Real-book results:**
- Flower Garden: title "The Flower Garden" (filename tier), author "T. Albert" (byline), language `en-GB` (catalog `/Lang`), cover designated, EPUBCheck 0 errors, **Ace 0/0/0/0**
- AI Projects: all frozen baseline metrics identical; title via heading tier; cover correctly omitted; Ace 0/0/0/0
- Corpus language spot check: Hands-On (junk `/Lang` b'\xff5') → `und` correctly; LinuxNotes (no `/Lang`) → `und`; TRANSFIMER → `en-US`; Writing Habit → `en`

**Reason:** The user approved these six workstreams as the P1 priority.
The policy decisions (stub + summary, remove claim, offline-only) were
explicit choices from the structured question. The user's qualification
on the language fallback: "Define an explicit, standards-compatible
fallback policy and test it."

---

### Phase D — README Documentation Fix (Commit `aae3e00`)

**What was instructed:**
The user's ZIP audit identified a P2 documentation-consistency finding:
README.md still described the removed `dcterms:conformsTo` WCAG-AA claim
as emitted metadata.

**What was executed:**
- README accessibility section: conformsTo line replaced with explicit
  negation ("the tool runs EPUBCheck and structural validation, never a
  WCAG audit, so it emits no conformance claim at all")
- `alternativeText` bullet updated to the real Round 2 gate
- Language policy documented (evidenced `/Lang`, `und` fallback)
- Stale "508 passed, 15 skipped" test count replaced with measured figures
- `src/pdf2epub.egg-info` removed locally (gitignored build artifact;
  regenerates from pyproject on next build)

**Reason:** P2 documentation consistency. The user said: "This is a
documentation consistency issue, not evidence that the claim remains in
generated EPUBs."

---

### Phase E — Round 3: Image Efficiency and Quality Instrumentation

#### E.1 — M0a: CI Workflow and Memory Gate (Commits `dee9e43`, `c6ecb21`, `870a449`, `d1f7415`)

**What was instructed:**
The user required a verified green CI baseline before any Round 3 work:
"Before implementing Round 3, verify the actual HEAD, clean working tree,
CI results, and baseline artifacts."

**What was executed — four iterations:**

| Iteration | Commit | Problem | Fix |
|---|---|---|---|
| 1 | `dee9e43` | CI run #1 failed with zero jobs: `${{ env.* }}` invalid in GitHub Actions job `name:` | Hardcode version in job name; in-file comment to prevent regression |
| 2 | `c6ecb21` | Run #2: 14/14 jobs executed; 2 macOS legs failed at "416/480 MB" memory budget | Platform-aware budget: Linux 400 MB, macOS 600 MB (evidence-based +25%) |
| 3 | `870a449` | Run #5: macOS 3.13 failed at "624 MB" — +30% swing on untouched code path. Investigation revealed **Darwin reports ru_maxrss in BYTES, Linux in KiB**; the "416/480/624 MB" figures were kilobytes. The gate also subtracted historical peaks (allocator noise, not conversion footprint). | Complete redesign: `tests/memprobe.py` fresh subprocess; platform-normalized units (Darwin bytes/1024², Linux KiB/1024 — both conventions unit-tested); no subtraction anywhere; single budget on every platform |
| 4 | `d1f7415` | Run #6 was 14/14 green but measurements lost to pytest's captured stdout. Direct Windows measurement: 58.9 MiB peak (GetProcessMemoryInfo; 200 MiB budget tightened from 400; ~3.4× headroom). GITHUB_STEP_SUMMARY channel added. | Run #7: 14/14 green with tightened budget |

**CI run history (all 14-job runs):**
| Run | Commit | Result | Notes |
|---|---|---|---|
| #1 | `aae3e00` | FAILURE (0 jobs) | Workflow validation: env context in job name |
| #2 | `dee9e43` | FAILURE (2 legs) | macOS memory budget |
| #3 | `c6ecb21` | **14/14 GREEN** | First complete execution ever |
| #4 | `5dd3135` | 14/14 GREEN | M0b |
| #5 | `ba935e9` | FAILURE (1 leg) | macOS 3.13 memory (led to correction) |
| #6 | `870a449` | 14/14 GREEN | Fresh-subprocess measurement |
| #7 | `d1f7415` | 14/14 GREEN | 200 MiB tightened budget |
| ... | ... | ... | (intermediate M3b runs) |
| #11 | `717c53d` | 14/14 GREEN | M3b OCR evidence record |
| #29 | `f22369b` | 14/14 GREEN | M3b merge |
| #30 | `95aabbb` | 14/14 GREEN | Round 3 consolidation |

**Reason:** The user's hard gate: "the remaining work should stay blocked
until that gate is demonstrably green." Each CI failure was investigated
to root cause before the next fix.

---

#### E.2 — M0b: Image Inventory (Commit `5dd3135`)

**What was instructed:**
The user's Round 3 plan stated: "Start with M0 and WS-1 only. Freeze the
current release boundary, establish the image inventory, and quantify the
size increase before changing the encoding code."

**What was executed:**
- `scripts/image_inventory.py` — committed reusable measurement tool that
  joins every packaged asset to its PDF origin via xref + bbox placement
  (never dimensions, which collide in real books)
- Attribution classes: `rendered-page-raster`, `mask-composite`,
  `mask-fallback`, `transcoded`, `passthrough`, `re-encoded`,
  `join-suspect`, `unmatched`
- Colorspace semantics aligned with the extraction gate's constants
  (component counts: 1=gray, 3=RGB, 4=CMYK)
- `docs/round3_image_inventory.md` — full attribution report
- Four baselines frozen:

| Document | SHA-256 | EPUB bytes | Key finding |
|---|---|---|---|
| Flower Garden | `e91fcea3...` | 10,543,872 | +3.6 MB entirely from 5 mask composites; 27 byte-identical JPEG passthroughs; ~0% eligible headroom (control case) |
| AI Projects | `369b95fe...` | 111,393 | 1 rendered-page raster; reference |
| C1 scan (Play, dance, Music therapies) | `d00068d2...` | 86,839,707 | 74 rendered rasters: 89.57 MB from 15.43 MB of source JPEGs (5.8×); M3a target |
| Hands-On GenAI | `20ca8b59...` | 51,763,248 | 180 JPX transcodes: 47.83 MB from 3.54 MB (13.5×); M3b target |

**Reason:** The user required measurement before any encoding policy change:
"Those actions would mix diagnosis with implementation and make regressions
harder to attribute."

---

#### E.3 — M3a: Page-Raster Optimization (Commit `ba935e9`)

**What was instructed:**
The user approved: JPEG q90 for eligible scanned-page rasters, q85-vs-q90
comparison, PNG fallback for alpha/encoder failure, dimensions unchanged.

**What was executed:**

| Aspect | Details |
|---|---|
| Change | `driver.py::_embed_visual_page`: `VISION_RASTER_JPEG_QUALITY = 90`; eligibility is **measured** (encode both, keep smaller) |
| Correction | A JPEG-only draft regressed the reference book (born-digital flat page: 125,022 PNG → 202,835 JPEG); the measured-eligibility rule was the fix |
| Fixture | `make_gradient_png()` added: deterministic photographic-like gradient; flat square changed because it legitimately stays PNG |
| Tests | 5 new failing-first tests: JPEG format + media-type + dimensions on photographic fixture; born-digital PNG kept; alpha guard; encoder failure → PNG; byte determinism |
| Benchmark | C1: 89,568,341 → 33,122,997 bytes (−63.0% rasters); EPUB 86,839,707 → 29,140,165 (−66.4%) |
| Quality | q90 vs q85 on 3 C1 pages: q85 saves only 13.9% extra with max diff 16-17/255 vs q90's 10-11; q90 stands |
| Validation | Real C1 artifact: structural PASS; EPUBCheck 0 errors; Ace 0/0/0/0; all 74 rasters dimension-identical |
| C3 | 2-page scan: 446,039 bytes (JPEG won both pages) |

**Test suite evolution:** 743 passed / 21 skipped

**Reason:** The user approved JPEG q90 with the quality protocol. The
measured-eligibility correction was made when the JPEG-only version
regressed the reference book's born-digital vision page.

---

#### E.4 — M3b: Embedded-Image Investigation (Multi-Phase)

**What was instructed:** The user provided a detailed multi-phase plan:

| Phase | Instruction summary |
|---|---|
| Phase 1 (Gate 1) | Record all 36 first-range verdicts; resolve Image 013 as LOSSLESS |
| Phase 2 (Gate 2) | Review all 147 images; assign explicit verdicts; zero PENDING at gate closure |
| Phase 3 | Recompute approved-candidate savings using only the final JPEG-ELIGIBLE set |
| Phase 4 | Compare Rules A/B/C against the 147-verdict ground truth; "evaluate the three documented rules — not newly invented alternatives" |
| Phase 5 | Pin the policy; lossless by default; M3a protected |
| Phase 6 | Write failing-first tests; "do not weaken a test simply because the current implementation fails it" |
| Phase 7 | Implementation: evidence-based; if current code is safe, no production changes needed |
| Phases 8–9 | Benchmark, validate, consolidate, release |

**What was executed per phase:**

**Phase 1 — Gate 1 (Commit `6869eec`):**
- Images 009, 017, 024, 025, 026, 031, 032, 034, 035, 036 recorded LOSSLESS
- Image 013 (xref 631) resolved LOSSLESS: "texture fidelity was not sufficiently established"
- Final tally 001–036: 18 JPEG-ELIGIBLE, 18 LOSSLESS, 0 PENDING
- Approved set: 21 candidates (18 + 3 OCR-positive reconsiderations)
- RULES.md created documenting all three candidate rules

**Phase 2 — Gate 2 (Commits `9708438`, `5cab22c` lineage):**
- Screening batch: 104 unresolved images in ZIP with manifest
- User reviewed all 104: all LOSSLESS by content-based reasoning (diagrams, charts, spectrograms, token examples, mixed composites, handwritten samples)
- Final tally 037–147: 3 JPEG-ELIGIBLE (048, 061, 062), 108 LOSSLESS
- All 147 resolved: 21 JPEG-ELIGIBLE + 126 LOSSLESS, 0 PENDING

**Phase 4 — Rule comparison (Commit `6c59134`):**
- Features computed for all 147 xrefs (deterministic, downsampled ≤128 px)
- All three rules evaluated with confusion matrices:

| Metric | Rule A | Rule B | Rule C |
|---|---|---|---|
| True approvals | 21 | 0 | 0 |
| False approvals | 109 | 80 | 31 |
| Missed opportunities | 0 | 21 | 21 |
| Precision | 0.162 | 0.000 | 0.000 |
| Recall | 1.000 | 0.000 | 0.000 |

- Root cause: all 21 approved photographs have low micro (0.0001–0.154)
  and high crisp (0.83–1.0) — the same signatures as text-bearing diagrams

**Phase 5 — Policy (Commit `f17fe2f`):**
- `M3B_POLICY.md`: lossless by default; no automatic JPEG through rejected
  rules; exception mechanisms deferred; alpha always lossless; M3a protected
- `PHASE5_DECISION.md`: approved decisions, rejected alternatives, unresolved
  questions, verified consistency check

**Phase 6 — Tests (Commit `0dcb987`):**
- `test_m3b_policy.py`: 13 tests covering all 9 policy requirements
- Architecture map: `_transcode_to_core` hardcodes PNG; no hidden lossy path;
  content-hash dedup; M3a unchanged
- One test correction: identity test needed body text for Tier 1 routing
- PHASE6_BASELINE.md

**Phase 6 correction (Commit `a11622b`):**
- M3a regression assertion tightened: must be JPEG specifically (not just
  "a valid core format")
- Size/fidelity tests relabeled as contract-documentation, not behavioral gates

**Phase 7 — Implementation decision:**
- No production changes needed; `_transcode_to_core` already hardcodes PNG
- The 13 policy tests are regression guards

**Merge (Commit `f22369b`):**
- `review/m3b-images` merged into main via `--no-ff`
- 233 files: 12 review docs, ~220 review artifacts, 1 test file
- Zero production .py files changed

**Consolidation (Commit `95aabbb`):**
- `docs/round3_record.md` updated: M3b section replaced with final findings
- Phase 7 closure, CI evidence, completion summary added
- Phase 9 consistency audit: 9/9 checks passed
- CI run #30: 14/14 green

**Test suite evolution at merge point:**
- Before M3b tests: 743 passed / 21 skipped
- After M3b tests: 757 passed / 23 skipped
- With M3b policy tests: 763 passed / 23 skipped (on quality-baseline)

**Key metrics (M3b):**
| Figure | Status |
|---|---|
| 73.4% projection (47.86→12.74 MB) | **Withdrawn** — based on refuted Rule A |
| 17.6% projection (47.24→38.90 MB) | **Withdrawn** — no validated automatic rule |
| Realized M3b saving | **0%** — the transcoded class stays lossless PNG |

**Reason:** The user directed each phase with specific conditions. The
investigation proved that the four features cannot reliably separate
photographs from text-bearing diagrams. The honest result is that the
safe behavior (lossless) was already enforced by the architecture.

---

### Phase F — Conversion Quality Baseline and Hyperlink Remediation

#### F.1 — Quality Baseline (Commit `c277241`)

**What was instructed:**
The user approved a Conversion Quality Baseline and Gap Analysis as the
next workstream: "Establish how well the converter preserves the meaning,
structure, and reading experience of PDFs. Only after that assessment
should you commit to the next feature."

**What was executed:**
- Architecture audit across 9 quality dimensions (text, reading order,
  structure, tables, notes, images, reflowability, EPUB validity,
  accessibility) with specific code locations and test coverage
- 4 representative documents converted with the unchanged baseline
- Confirmed defects:

| Defect | Severity | Evidence |
|---|---|---|
| LINK-001: PDF URI annotations not extracted | High | 91 missing external URIs (89 LinuxNotes, 2 AI_Projects) |
| LINK-002: PDF internal links not extracted | Medium | 238 missing internal links (208 LinuxNotes, 30 arch_ref) |
| NOTE-001: Footnotes as disconnected prose | Medium-High | 32 pages of unassociated bottom text in arch_ref |

- No defects in text fidelity, headings, images, or EPUB validity
- OCR of scanned pages, aligned tables, digest furniture documented as
  known limitations from prior rounds

**Reason:** The user approved: "Proceed with Phase B and Phase D on a
dedicated branch. Keep main unchanged."

---

#### F.2 — Whole-Element Hyperlink Extraction (Commit `d442818`)

**What was instructed:**
The user conditionally approved with four safeguards and two corrections:
1. Whole-element wrapping with coverage guard (annotation must cover ≥60% of element)
2. URI whitelist (http/https/mailto) with normalization
3. Internal links to vision pages: chapter-level fallback
4. Image links deferred but counted
5. Multiple-occurrence matches: REJECT as ambiguous (not link-first)
6. Preserve page-specific annotation metadata at extraction time

**What was executed:**
- `extract_page_links()`: collects LINK_URI and LINK_GOTO annotations;
  captures `clip_text` and `source_page` at extraction time
- `apply_link_annotations()`: coverage-guarded whole-element mapping
- `StreamElement` gained `link_uri` and `link_target_page` fields
- `render()` applies link at render time with duplicate prevention
- Internal GOTO resolution via page-to-chapter mapping in packaging
- 6 failing-first tests: URI annotation, text URL preserved, unsupported
  scheme, no duplicates, GOTO chapter link, no links on clean PDF
- Full suite: 763/23/0

**Real-corpus results (honest):**
| Document | URIs before | URIs after | Internal before | Internal after |
|---|---|---|---|---|
| LinuxNotes | 4/93 | 7/93 | 0/208 | 2/208 |
| AI_Projects | 1/3 | 1/3 | 0/0 | 0/0 |
| arch_ref | — | — | 0/30 | 0/30 |

**Reason:** Limited improvement — the 60% coverage guard correctly rejects
most real-world annotations that cover short phrases within larger paragraph
elements. The evidence identified sub-span linking as the needed follow-up.

---

#### F.3 — Sub-Span Link Mapping (Commit `c2029d8`)

**What was instructed:**
The user approved the sub-span plan with two required changes:
1. Reject multiple-occurrence matches as ambiguous (not link-first)
2. Preserve page-specific annotation metadata during extraction

Additional corrections:
- Keep link-mapping logic in a focused helper module (`engine/link_mapper.py`)
- Use `page.get_text("text", clip=rect)` as initial technique, validate results
- Check overlapping link ranges with different destinations → reject
- Apply after welding/stripping, before normalization

**What was executed:**
- `engine/link_mapper.py` created: `map_subspan_links()` with text matching,
  ambiguity rejection, overlap detection, whole-element fallback
- `extract_page_links()` now captures `clip_text` per annotation
- `driver.py` collects annotations from ALL Tier 1 pages (not just from
  `build_page_stream` internal calls)
- `build_epub_publication` gained `page_annotations` parameter
- `map_subspan_links()` called after `process_element_stream`, before
  `normalize_semantics`
- `mailto:` added to structural check's external-link skip list (was being
  validated as broken internal reference)
- Full suite: 763/23/0

**Real-corpus results:**
| Document | URIs (before sub-span) | URIs (after) | Internal (before) | Internal (after) |
|---|---|---|---|---|
| LinuxNotes | 7/93 | 10/93 | 2/208 | 6/208 |
| AI_Projects | 1/3 | 2/3 | 0/0 | 0/0 |
| arch_ref | — | — | 0/30 | 0/30 |

**Reason:** The modest improvement (10/93 vs target >50) led to the
failure-ledger investigation — the evidence showed the text-matching
hypothesis was not the bottleneck.

---

#### F.4 — Per-Annotation Failure Ledger (Commit `5cab22c`)

**What was instructed:**
The user required: "Produce a per-annotation failure ledger. For each
missing LinuxNotes URI and architecture-reference GOTO, record whether the
annotation was collected, whether its destination resolved, whether clipped
text matched the element, and why linking was rejected or omitted."

**What was executed:**
- 490 annotations traced (485 LinuxNotes + 5 AI_Projects)
- Each assigned exactly one `primary_failure_stage`

| Stage | Count | Share |
|---|---|---|
| **collection** | **322** | **69.2%** |
| destination_resolution | 113 | 24.3% |
| candidate_geometry | 21 | 4.5% |
| clip_text | 9 | 1.9% |
| text_matching | **0** | **0%** |
| ambiguous | **0** | **0%** |

- **Critical finding**: text matching is NOT the bottleneck (0 failures);
  collection is the dominant gap (69.2% of annotations are on Tier 2 pages
  that the driver never examines)
- arch_ref's 30 LINK_NAMED (kind=4) links not captured by the kind filter —
  separate implementation gap
- `docs/link_failure_ledger.md` + `docs/link_failure_ledger.json`

**Reason:** The user required evidence-based diagnosis before further
implementation: "Character-level geometry, Tier 2 annotation collection,
and GOTO resolution should remain competing hypotheses until the ledger
provides evidence."

---

#### F.5 — Tier 2 Feasibility Investigation (Commit `eeecdbd`)

**What was instructed:**
The user required: "Determine whether collecting annotations from Tier 2
pages can recover links, and whether the resulting annotations can be
mapped to actual output elements."

**What was executed:**
- Ledger reconciled: 465 failed + 25 linked = 490; categories mutually exclusive
- 319 LinuxNotes collection failures traced to source pages and routing targets:

| Category | Pages | Failures | Routing | Text in output? |
|---|---|---|---|---|
| TOC pages (1, 2, 62) | 3 pages | **243 (75.5%)** | TIER2_VISION_OCR | **No** (raster image in offline mode) |
| Non-TOC digest pages | 23 pages | **73 (23%)** | TIER2_LLM_DIGEST | **Yes** (digest fallback produces text) |
| Non-TOC vision page | 1 page | 3 | TIER2_VISION_OCR | **No** |

- Key finding: 75.5% of collection failures are on **table-of-contents
  pages** routed to vision — the TOC's two-column layout with dot leaders
  (vector graphics) triggers `columnar_cooccurrence:-20, vector_density:-30`
  even though the pages contain plain text
- The remaining 23% are on digest-routed pages where `_digest_fallback`
  produces text elements with correct `page_num` and geometry — annotations
  CAN be mapped
- `docs/tier2_feasibility_report.md`

**Remediation recommendation (from evidence):**
| Priority | Change | Expected recovery | Risk |
|---|---|---|---|
| 1 | Extend annotation collection to all pages | ~73 annotations | Low |
| 2 | Add LINK_NAMED support (kind=4) | 30 arch_ref annotations | Low |
| Not recommended | Character-level geometry | 0 (no text-matching failures) | N/A |
| Separate workstream | Router change for TOC pages | 243 annotations | Medium |

**Reason:** The user's qualification: "collection should not imply that
every annotation is eligible for linking." The investigation confirmed
that 246 of 319 collection failures are on vision-routed pages with no
text output — collecting them alone would not produce valid links.

---

## Section 2 — Status Tracking

### Completed ✅

| # | Item | Status | Commit | Key evidence |
|---|---|---|---|---|
| 1 | Round 1: Image fidelity (masks, headings, paragraphs) | ✅ | `e6614c5` | 22 tests; Flower Garden: 39→35 assets, 10→0 h4s, 191→0 strongs; EPUBCheck clean |
| 2 | Round 2: Metadata derivation (title, author, language, cover) | ✅ | `8392239` | 33 tests; Flower Garden: "The Flower Garden"/"T. Albert"/`en-GB`/cover designated; EPUBCheck+Ace clean |
| 3 | Round 2: Alt-text honesty (caption-derived vs location-only) | ✅ | `8392239` | `alt_source` field; `alternativeText` gated; summary honest |
| 4 | Round 2: ConformsTo removal | ✅ | `8392239` | Unconditional WCAG-AA claim entirely removed |
| 5 | Round 2: xml:lang on OPF package | ✅ | `8392239` | `_set_package_xml_lang()` post-write patch; Ace epub-lang fixed |
| 6 | Round 2: Doctor four-state diagnostics | ✅ | `8392239` | Env-var presence, provider selection, credential validation, model smoke |
| 7 | Round 2: --language CLI flag | ✅ | `8392239` | Threaded through ConversionRequest into engine |
| 8 | README documentation fix | ✅ | `aae3e00` | Stale WCAG claim removed; alt-text updated; test counts corrected |
| 9 | M0a: CI workflow fix (env context in job names) | ✅ | `dee9e43` | Run #2: 14 jobs created (first ever) |
| 10 | M0a: Memory gate correction (platform-aware budget) | ✅ | `c6ecb21` | Run #3: 14/14 green (first complete execution) |
| 11 | M0a: Memory gate redesign (fresh subprocess, unit correction) | ✅ | `870a449` | `tests/memprobe.py`; Darwin bytes/Linux KiB normalized; no subtraction |
| 12 | M0a: Memory budget tightening (200 MiB from measurement) | ✅ | `d1f7415` | 58.9 MiB measured; run #7: 14/14 green |
| 13 | M0b: Image inventory and attribution | ✅ | `5dd3135` | `scripts/image_inventory.py`; 4 baselines; Flower Garden control case confirmed |
| 14 | M3a: Page-raster optimization | ✅ | `ba935e9` | C1: −66.4%; q90 approved; 5 tests; EPUBCheck+Ace clean |
| 15 | M3b: OCR pre-screen | ✅ | `717c53d` | RapidOCR; 111/147 text-positive; evidence recorded |
| 16 | M3b: 147-image visual review | ✅ | `9708438` | All verdicts recorded; Gate 2 closed; 0 PENDING |
| 17 | M3b: Rule A/B/C comparison | ✅ | `6c59134` | All three rejected; confusion matrices documented |
| 18 | M3b: Policy pinned (lossless by default) | ✅ | `f17fe2f` | `M3B_POLICY.md`; M3a protected; exceptions deferred |
| 19 | M3b: Policy enforcement tests | ✅ | `0dcb987` | 13 tests; all pass; architecture mapped; no hidden lossy paths |
| 20 | M3b: Test corrections (M3a assertion, contract labels) | ✅ | `a11622b` | M3a must be JPEG specifically; size/fidelity labeled contract docs |
| 21 | M3b: Consolidation and merge to main | ✅ | `f22369b`, `95aabbb` | `--no-ff` merge; 233 files; zero production .py changes; CI #30 14/14 |
| 22 | Round 3 record consolidation | ✅ | `95aabbb` | 9/9 consistency audit; M3b marked complete; Phase 7 closure |
| 23 | Quality baseline audit | ✅ | `c277241` | LINK-001/002/NOTE-001 quantified; no other defects |
| 24 | Whole-element hyperlink extraction | ✅ | `d442818` | 6 tests; 763/23/0; LinuxNotes 7/93 URIs |
| 25 | Sub-span link mapping | ✅ | `c2029d8` | `engine/link_mapper.py`; 763/23/0; LinuxNotes 10/93 URIs |
| 26 | Per-annotation failure ledger | ✅ | `5cab22c` | 490 records; collection=69.2%; text_matching=0% |
| 27 | Tier 2 feasibility investigation | ✅ | `eeecdbd` | 73 recoverable/246 unrecoverable; TOC pages identified |
| 28 | Complete session record compiled | ✅ | `ad08950` | This document |

### Left To Do (Not Yet Started) 📋

| # | Item | Priority | Prerequisites | Expected impact | Notes |
|---|---|---|---|---|---|
| 1 | **Tier 2 annotation collection** (digest-routed pages) | High | Tier 2 feasibility ✅ | ~73 annotations recovered | Extend collection from `tier1_indices` to all pages; smallest safe change; the 246 vision-routed annotations will be naturally dropped by the mapper's existing candidate-finding logic |
| 2 | **LINK_NAMED support** (kind=4) | Medium | None | 30 arch_ref annotations | Extend `extract_page_links()` kind filter; verify each annotation has a resolvable `page` target; reject unsupported named destinations |
| 3 | **Destination-resolution investigation** | Medium | Failure ledger ✅ | 113 annotations potentially recovered | Text matched but URI didn't appear in EPUB; needs diagnostic logging at each pipeline stage (mapper → welding → stripping → normalization → packaging) |
| 4 | **Footnote/endnote support** (NOTE-001) | Medium-High | None | 32 pages of disconnected footnote text | Requires marker detection, note association, EPUB navigation semantics (`epub:footnote`), and return navigation — a full design phase |
| 5 | **Router refinement for TOC pages** | Low (separate workstream) | None | 243 GOTO links + text recovery | Keep TOC-shaped pages (two-column layout with dot leaders, plain text content) on Tier 1; affects all extraction, not just links |
| 6 | **Corpus validation after Tier 2 fix** | Required after fix #1 | Tier 2 collection implemented | Measurement of actual improvement | Re-run LinuxNotes, AI_Projects, arch_ref; compare against `eeecdbd` baseline |
| 7 | **Merge quality-baseline to main** | After all fixes verified | Fixes #1–#3 validated | Link preservation improvements on main | Currently 7 commits ahead; merge only after evidence review |
| 8 | **EPUB inspection in a reader** | After link fixes | Links present in output | Verify clickable links work | Open EPUB in a real reader; check link destinations resolve correctly |
| 9 | **Visual regression testing** | Backlog | None | Automated layout checking | Standing deferral from prior rounds; not yet scoped |

### Drifted From (Started but Changed Direction) 🔄

| # | Item | Original direction | What actually happened | Reason for the drift |
|---|---|---|---|---|
| 1 | M3b: Embedded-image JPEG transcoding | Planned to implement a three-outcome classifier (photographic/line-art/uncertain) and selectively JPEG-compress the 47.86 MB transcoded class | Investigation proved no reliable classifier exists; policy decision: **lossless by default**; no encoder built; realized saving **0%** | The 147-image review showed the four features (micro, flat, crisp, colors) produce the same signatures for photographs and text-bearing diagrams. Rules A (109 false approvals), B (0 true approvals, 80 false), C (0 true, 31 false) were all refuted. Implementing any of them would have introduced lossy encoding of lossless-required content |
| 2 | 73.4% size-reduction projection | Expected to reduce the Hands-On EPUB from 47.86 MB to 12.74 MB | Projection **withdrawn**; the 17.6% and 27.7% projections also withdrawn; the honest near-term result is no additional compression | The permissive Rule A that produced 73.4% was refuted by the OCR pre-screen (111/147 text-positive). No validated automatic rule exists to select eligible images |
| 3 | Character-level geometry mapping for link text matching | Proposed as the next refinement after sub-span linking showed limited real-world coverage (10/93 vs target >50) | The failure ledger showed **0 text-matching failures**; the dominant gap is annotation **collection** (69.2%), not text precision | Evidence-based redirection: the text matching works correctly when annotations are collected and elements overlap. The bottleneck is that 322 annotations are on Tier 2 pages never examined by the driver |
| 4 | Platform-aware memory budget (400 Linux / 600 macOS) | Initially implemented as a platform-specific calibration | Replaced entirely with fresh-subprocess measurement (`tests/memprobe.py`) with platform-normalized units and a single 200 MiB budget | Darwin reports `ru_maxrss` in **bytes**, Linux in **KiB** — the platform-split budget was based on mislabelled units (the "416/480/624 MB" figures were kilobytes). The corrected approach measures the conversion's own peak in a fresh process with normalized units, no subtraction |
| 5 | OCR pre-screen as a text-matching improvement | Initially proposed to improve link text matching precision | OCR was used for **image content classification** (identifying text in images) rather than link text matching; the failure ledger later showed text matching has 0 failures | The OCR pre-screen's purpose was to identify text-bearing images during the M3b investigation, not to improve link extraction. Its findings (111/147 text-positive) contributed to rejecting Rule A |

### Abandoned (Explicitly Rejected) ❌

| # | Item | Status | Reason for rejection |
|---|---|---|---|
| 1 | WCAG-AA conformance claim | ❌ Removed in Round 2 | The tool never ran a WCAG audit; an unconditional `dcterms:conformsTo` claim would mislead readers and distributors |
| 2 | Image-targeted link annotations | ❌ Deferred in Phase F | Different markup semantics (wrapping `<figure>` in `<a>`); not tested; counted as a known limitation in the defect register |
| 3 | OCR of scanned pages | ❌ Out of scope | Tier policy: vision pages embed rasters offline; OCR is a model/feature decision, not a defect |
| 4 | q85 JPEG for scanned pages | ❌ Rejected by evidence | q85's 13.9% additional saving is not material against max diff 16-17/255 vs q90's 10-11/255 (user's own criterion: "choose q85 only if its additional savings are material and the visual difference remains acceptable") |
| 5 | JPEG-only page-raster encoding (no PNG fallback) | ❌ Rejected during M3a | A JPEG-only version regressed the reference book's born-digital vision page from 125,022 to 202,835 bytes; the measured-eligibility rule (encode both, keep smaller) replaced it |

### Known Limitations (Documented, Not Fixable in Current Scope) ⚠️

| # | Limitation | Disposition | Reason |
|---|---|---|---|
| 1 | Scanned pages are full-page rasters (no OCR) | Out of scope | Documented tier policy; requires a model or Tesseract dependency |
| 2 | Vision-routed TOC pages produce no text output | Router design | 243 GOTO links on TOC pages lost in offline mode; a router change is a separate workstream |
| 3 | 113 destination-resolution failures | Under investigation | Text matched but URI not in EPUB output; needs pipeline-stage tracing (mapper → welding → normalization → packaging) |
| 4 | Aligned tables stay prose | By design | No-fabrication rule: cleanly-aligned pairs are indistinguishable from two-column prose |
| 5 | Digest-page furniture below position-evidence guard | Deferred | Cross-page text-echo needed; low value while model path owns those pages |
| 6 | `we re ready to open` (Flower Garden p.22) | Source-level defect | ToUnicode gap in the source PDF (apostrophe genuinely absent from text layer); not a conversion error |
| 7 | Image size PNG inflation (M3b path) | Correct by policy | M3a handles scanned-page rasters; M3b embedded images stay lossless (the approved, tested policy) |
| 8 | arch_ref 30 LINK_NAMED (kind=4) not captured | Implementation gap | `extract_page_links()` only handles LINK_URI (kind=2) and LINK_GOTO (kind=1); named destinations excluded |
| 9 | 246 vision-routed collection failures | Architecture | TOC pages (243) + page 47 (3) produce raster images with no text elements; annotation collection alone cannot recover these links |

---

## Test Suite Evolution (Through the Session)

| Checkpoint | Passed | Skipped | Failed | Notes |
|---|---|---|---|---|
| Pre-Round 1 (baseline) | 684 | 18 | 0 | EPUBCheck hidden |
| After Round 1 | 706 | 20 | 0 | +22 tests; offline |
| With EPUBCheck visible | 710 | 16 | 3 (Ace) | 3 Ace violations identified as Round 2 scope |
| After Round 2 | 740 | 19 | 0 | +33 tests |
| After M0b inventory | 740 | 19 | 0 | No new tests |
| After M3a | 743 | 21 | 0 | +5 vision raster tests |
| After M3b Phase 6 | 757 | 23 | 0 | +13 policy + 1 fixture |
| After link extraction | 763 | 23 | 0 | +6 link tests |
| After sub-span mapping | 763 | 23 | 0 | Same count (refactoring) |
| Current (quality-baseline) | 763 | 23 | 0 | Stable |

## CI Run History (Key Runs)

| Run | Commit | Jobs | Result | Trigger/Notes |
|---|---|---|---|---|
| #1 | `aae3e00` | 0/14 | FAILURE | Workflow validation: env context in job name |
| #2 | `dee9e43` | 14/14 | FAILURE (2 legs) | macOS memory budget failures |
| #3 | `c6ecb21` | 14/14 | **GREEN** | First complete execution ever |
| #4 | `5dd3135` | 14/14 | GREEN | M0b inventory |
| #5 | `ba935e9` | 13/14 | FAILURE (1 leg) | macOS 3.13 memory — led to the unit correction |
| #6 | `870a449` | 14/14 | GREEN | Fresh-subprocess measurement |
| #7 | `d1f7415` | 14/14 | GREEN | 200 MiB tightened budget |
| #11 | `717c53d` | 14/14 | GREEN | M3b OCR evidence record |
| #29 | `f22369b` | 14/14 | GREEN | M3b merge (233 files, no production changes) |
| #30 | `95aabbb` | 14/14 | GREEN | Round 3 record consolidation |

---

## Branch State Summary

| Branch | HEAD | Status | Relationship to main | Total commits |
|---|---|---|---|---|
| `main` | `95aabbb` | Stable; Round 3 complete | Production branch | 95 commits |
| `quality-baseline` | `ad08950` | Active; hyperlink remediation | **7 commits ahead** of main | 102 commits |
| `review/m3b-images` | `3201282` | Merged into main at `f22369b` | Historical (M3b review) | 18 commits |

### Commits on `quality-baseline` (not yet on main)

| Commit | Description | Production code changed? |
|---|---|---|
| `c277241` | Quality baseline defect register | No (docs only) |
| `d442818` | Whole-element hyperlink extraction | **Yes** (tier1_classifier.py, driver.py, packaging) |
| `c2029d8` | Sub-span link mapping | **Yes** (link_mapper.py, tier1_classifier.py, driver.py, packaging) |
| `5cab22c` | Per-annotation failure ledger | No (docs only) |
| `eeecdbd` | Tier 2 feasibility report | No (docs only) |
| `ad08950` | Complete session record (this file) | No (docs only) |

Production files changed on this branch (not yet on main):
- `src/pdf2epub/engine/tier1_classifier.py` — link extraction + annotation capture
- `src/pdf2epub/engine/driver.py` — annotation collection from Tier 1 pages
- `src/pdf2epub/engine/packaging_and_validation.py` — page_annotations param, sub-span pass, mailto: fix
- `src/pdf2epub/engine/link_mapper.py` — new file (sub-span mapping)
- `tests/engine/test_link_extraction.py` — new file (6 tests)

---

## Quality Metrics Summary

### EPUB size benchmarks (Round 3 final)

| Document | Before M3a | After M3a | Reduction |
|---|---|---|---|
| C1 scan (74 vision pages) | 86,839,707 bytes | 29,140,165 bytes | **−66.4%** |
| Reference (AI Projects) | 111,393 bytes | 111,392 bytes | Unchanged (correct) |
| C3 scan (2 pages) | ~0.7 MB | 446,039 bytes | Informational |

### M3b honest savings

| Figure | Status |
|---|---|
| 73.4% projection | **Withdrawn** (based on refuted Rule A) |
| 17.6% projection | **Withdrawn** (no validated automatic rule) |
| **Realized M3b saving** | **0%** (transcoded class stays lossless PNG) |

### Hyperlink coverage evolution

| Stage | LinuxNotes URIs | LinuxNotes internal | AI_Projects URIs | arch_ref internal |
|---|---|---|---|---|
| Baseline (no link extraction) | 4/93 | 0/208 | 1/3 | 0/30 |
| Whole-element (d442818) | 7/93 | 2/208 | 1/3 | 0/30 |
| Sub-span (c2029d8) | 10/93 | 6/208 | 2/3 | 0/30 |

### Failure ledger distribution (490 annotations)

| Primary failure stage | Count | Share |
|---|---|---|
| collection (Tier 2 pages) | 322 | 69.2% |
| destination_resolution | 113 | 24.3% |
| candidate_geometry | 21 | 4.5% |
| clip_text | 9 | 1.9% |
| text_matching | 0 | 0% |
| ambiguous | 0 | 0% |
| Successfully linked | 25 | — |

---

*This document was compiled from the complete session history (71 commits,
30+ CI runs, all user instructions, all test results, all corpus
measurements). It is the authoritative record of what was decided, what
was done, what changed direction, what remains, and the reasoning for
each — intended as the working reference for the next session.*
