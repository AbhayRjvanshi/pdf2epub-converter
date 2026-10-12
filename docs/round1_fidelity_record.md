# Round 1 Fidelity Record — Image, Heading and Paragraph Correctness

Date: 2026-10-12
Scope: Round 1 of the evidence-backed remediation program (the three
confirmed P0 workstreams). Metadata recovery, cover designation,
accessibility-conformance changes, doctor diagnostics and routing
redesign are deliberately out of scope and unchanged.

Source document
---------------

* File: `20250926124047041_THE_FLOWER_GARDEN_Free_Childrens_Book_By_Monkey.pdf`
* SHA-256: `e91fcea3b9d46b1432624d78d257973a53b53417a578698ddc4500b1fe075015`
* 32 pages, SegoePrint-Bold decorative all-bold typography, 94.1% of
  sampled body characters bold.
* Conversion: offline (`llm_adapter=None`), routing 28 tier1 / 4
  tier2-digest / 0 tier2-vision — identical to the original run.

What was fixed, where, and why
------------------------------

### WS1 — Image fidelity (`engine/tier1_classifier.py`)

1. **/SMask transparency is composited.** `extract_images` previously
   read only `block["image"]` and discarded `block["mask"]`, so the five
   masked full-page illustrations (pages 6, 10, 11, 29, 31) lost their
   alpha. `_composite_with_mask` now merges base+mask into one
   alpha-carrying PNG (`fitz.Pixmap(base, mask)`); on any decode or
   dimension mismatch the opaque base survives with a warning.
2. **Renderer-synthesized mask rasters are dropped.** The page-6
   828x335 grayscale artifact came from MuPDF rasterizing an ExtGState
   luminosity soft mask into a dict image block. The drop rule requires
   corroborating evidence: grayscale colorspace, no backing image xref
   (matched via `page.get_image_info(xrefs=True)`), an /SMask'd image on
   the page, and bbox overlap with that image's placement.
3. **Solid transparency-group backplates are dropped** (pages 31/32
   all-white buffers): synthesized placement + uniform decoded pixels.
   Content-based, not bbox-based.
4. **Duplicate identical placements deduplicate** on bbox + content
   hash, not geometry alone.
5. **CMYK gate extended to core extensions**: a `jpeg`/`png` block whose
   reported colorspace is not gray/RGB now transcodes; conversion
   verified non-inverting (k-only swatch renders near-black, not white).

### WS2 — Heading demotion and emphasis (`engine/heading_signals.py`,
`engine/tier1_classifier.py`, `engine/tier2_llm_handler.py`,
`engine/confidence_router.py`, `engine/driver.py`)

1. `DocumentFontProfile` now measures `bold_char_share` (char-weighted,
   same sampling pass as the size baseline) and derives
   `bold_is_structural` (`< BOLD_NOISE_SHARE = 0.60`, a tunable
   heuristic documented at the constant).
2. The ten false h4s were produced by the *size ladder* (22pt text vs
   20pt modal body, ratio 1.1, bold), not the structural pass: the
   ladder's bold argument now receives `is_bold(...) and
   profile.bold_is_structural`.
3. `structural_heading_level` takes `bold_is_structural`; wording
   evidence (`_is_title_like`) still promotes same-family headings —
   not a font-identity veto.
4. `<strong>` emission is a separate decision from heading promotion:
   document-norm boldness in the body font family (`font_family`
   normalization strips weight/style tokens) emits no `<strong>`. Bold
   spans in any other font keep the tag (inline-emphasis fixture and
   the AI Projects reference still emit 25 legitimate strongs).
5. Digest parity: `Tier2Request.bold_is_structural` threads the same
   evidence into `_digest_fallback`, and `build_layout_digest` now
   derives bold via `is_bold` (flags + font-name hints) so tier1/tier2
   cannot disagree about boldness.

### WS3 — Paragraph reconstruction (`engine/tier1_classifier.py`,
`engine/tier2_llm_handler.py`)

`build_paragraphs` previously required `same_block`, so one-line-per-
block books shattered wrapped sentences into per-line `<p>` elements.
Cross-block merging is now allowed through `_continues_across_blocks`,
which is over-determined by design: same tag, size within 0.6pt, same
font family, x-range overlap >= 50% of the shorter line, left edges
within 2 font sizes, neither line list-marked, previous line not
sentence-terminating, next line lowercase-initial — plus the caller's
same-flow vertical test. Any missing evidence keeps the blocks split.
The digest fallback gained the identical rule (`_cross_block_continues`).
`_should_weld` is untouched: cross-page welds are recorded, not
maximized.

### Engine boundary hardening (`engine/driver.py`)

`run_pipeline` now normalizes empty/None `title`/`author` to the
sentinels before metadata assembly; a literal None previously produced
`<title/>` and a non-conformant EPUB (found while wiring the
integration test — production callers were unaffected).

Verification evidence
----------------------

### Offline test suite (deterministic environment)

* Baseline commit: `4bff243` ("Record the magazine corpus session and the
  completion review"), the checkout immediately before Round 1.
  Environment: Windows 10, project `.venv` (Python 3.10, pymupdf 1.28.2,
  ebooklib, lxml per requirements.txt), `NVIDIA_API_KEY` cleared for the
  child process so live-provider tests skip.
* Command: `.venv\Scripts\python.exe -m pytest` with the npm global bin
  dir removed from `PATH` (EPUBCheck/Ace unresolvable, matching the CI
  default environment where both are "not installed" and honestly
  skipped).
* Baseline before Round 1: **684 passed, 18 skipped, 0 failed (~67s)**.
* After Round 1: **706 passed, 20 skipped, 0 failed (~35s)**.
  +22 new tests (12 image fidelity, 5 heading/emphasis, 3
  cross-block/paragraph, 2 env-gated integration skips).
* With EPUBCheck installed and Ace temporarily disabled (the environment
  of the earlier project records): **710 passed, 16 skipped, 0 failed
  (~9 min; EPUBCheck also runs inside every pipeline conversion)**.
  This confirms Round 1 kept every fixture EPUB conformance-clean.
* Baseline-count reconciliation: the earlier project record of
  "688 passed / 14 skipped" and this record's 684/18 differ by exactly
  the 4 EPUBCheck-gated conformance tests
  (`test_epubcheck_conformance` + 3 parametrized fixtures in
  `tests/engine/test_end_to_end.py`), which run when EPUBCheck is
  resolvable and skip otherwise. 688/14 = EPUBCheck visible;
  684/18 = EPUBCheck hidden. Same source revision, same tests.
* Known environment sensitivity (pre-existing, unchanged by Round 1):
  with Ace by DAISY installed and visible, three offline e2e tests fail
  because Ace reports serious `epub-lang` / `document-title` /
  `empty-heading` violations on fixture output. Recorded as Round 2
  candidates; this machine's `ace 1.4.6` post-dates the recorded
  baseline environment.
* With `NVIDIA_API_KEY` present, `tests/providers/test_live_nvidia.py`
  runs live network tests (separate opt-in by design).

### Real-book integration (env-gated, `PDF2EPUB_FLOWER_PDF`)

`tests/integration/test_flower_garden.py` — skipped deterministically
when the variable is unset; passed against the source above:

* No false headings: none of the ten page-24 fragments appears in any
  h1-h6 or in `nav.xhtml`; "Your Story Book!" survives as a heading.
* No `<strong>` in any chapter body.
* Cross-block joins present (e.g. "mom and dad. They ran" exists only
  when wrapped lines merged).
* No 828x335 grayscale asset packaged; >= 5 alpha-carrying PNGs; 35
  assets exactly (39 before, 4 renderer artifacts removed).
* EPUBCheck (locally installed 5.x via npm): **0 errors / 0 warnings**
  on the freshly converted book. When EPUBCheck is absent the test
  skips with "not installed; conformance not run" — never silently
  passing.

### Before/after metrics (old artifact vs fresh conversion)

| metric | BEFORE | AFTER |
|---|---|---|
| media assets | 39 | 35 |
| 828x335 gray mask artifacts | 1 | 0 |
| alpha-carrying PNGs | 6 | 8 |
| h4 elements (page-24 class) | 10 | 0 |
| `<strong>`-wrapped body lines | 191 | 0 |
| paragraph elements | 145 | 130 |
| nav TOC entries | 12 (10 false fragments) | 2 |
| EPUB media bytes | 7.0 MB | 10.6 MB |

Honest notes on the metrics:

* **Size regression is real and expected**: the five masked JPEG
  illustrations composite to RGBA PNG (~7x inflation, the corpus-record
  JPEG-vs-PNG observation). Image size policy is deferred to Round 3 by
  scope agreement; no content was sacrificed for size.
* **Paragraphs 145 -> 130**: fifteen cross-block joins; the page-24
  narrative now reconstructs as full sentences. Centered interjection
  lines ("hurry!", "gardens.", "mom said.") stay separate by the
  left-alignment rule — visually faithful for this book.
* **Welds: 0** on the real book, recorded not asserted. This book's
  pages end on complete sentences, so zero is the faithful outcome;
  `_should_weld` was not changed.

### Cross-document regression

* Full synthetic corpus green (magazine, scanned, JPX, two-column,
  interleaved columns, tables, lists, hyphens, special characters).
* AI Projects reference PDF (`C:\Users\rajva\Downloads\
  Artificial_Intelligence_Projects.pdf`): conversion success, routing
  4 tier1 / 1 digest / 1 vision, 18 headings, 25 legitimate `<strong>`
  (mixed typography: bold evidence correctly still structural),
  content probes intact.

Skipped checks (recorded, not claimed)
---------------------------------------

* **Ace by DAISY**: not run against the real book in this round. Locally
  Ace flags pre-existing packaging gaps (xml:lang on the package
  element, empty chapter `<title>` elements, one empty heading) that
  are Round 2 scope; running it would fail the gate for defects this
  round did not set out to fix. CI defers Ace by design.
* **Reader rendering screenshots**: not in this round's scope.
* **Live provider conversion** (Kimi K3 digest pages): the 4 digest
  pages were verified through the deterministic fallback path plus
  unit tests for the model-independent evidence threading.

Known limitations (unchanged, for later rounds)
----------------------------------------------

1. `we re ready to open` (page 22): the apostrophe is genuinely absent
   from the PDF's text layer (raw MuPDF extraction contains a literal
   space; verified codepoint-by-codepoint). Source-level ToUnicode
   defect, not a conversion error; a contraction-repair heuristic or
   vision OCR tier could address it later.
2. Metadata sentinels ("Untitled Publication"/"Unknown Author"), no
   cover-image property, unconditional WCAG conformance claim, stub alt
   text, doctor credential-state collapsing: confirmed Round 2 items,
   untouched.
3. Routing has a single layout score (no separate visual confidence);
   unchanged by agreement.

Commands (reproducibility)
--------------------------

```
# offline deterministic suite (CI-like environment)
$env:NVIDIA_API_KEY = $null
$env:Path = <npm global bin removed>
.venv\Scripts\python.exe -m pytest

# real-book gates + EPUBCheck
$env:PDF2EPUB_FLOWER_PDF = <path to the Flower Garden PDF>
.venv\Scripts\python.exe -m pytest tests\integration
```

Line-ending note (audit follow-up)
----------------------------------

An independent audit of an extracted archive saw whole-file diffs on
`tests/engine/test_end_to_end.py` and `tests/package/`
`test_package_skeleton.py`. Those files have **zero content diff** in
this checkout (`git diff --numstat` is empty; their index entries are LF
and the working copies are CRLF, which `core.autocrlf=true` normalizes).
The noise is an artifact of extracting the archive on Linux without the
repository's line-ending configuration. `.gitattributes` now declares
`* text=auto` plus explicit binary rules so future cross-platform
snapshots cannot produce line-ending-only diffs.
