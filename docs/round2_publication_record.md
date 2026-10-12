# Round 2 Publication Record — Metadata, Cover, Alt-Text Honesty, Packaging Claims, Doctor Diagnostics

Date: 2026-10-13
Scope: the six confirmed-open P1 workstreams from the Round 1 record
and the audit catalogue. Routing redesign, image-size policy and the
broader investigation list are **out of scope by decision**, exactly
as agreed; no router or transcoding behavior changed this round.

Source document (unchanged, re-verified):

* File: `20250926124047041-THE-FLOWER-GARDEN-Free-Childrens-Book-By-Monkey-Pen.pdf`
* SHA-256: `e91fcea3b9d46b1432624d78d257973a53b53417a578698ddc4500b1fe075015`
* Baseline commit: `e6614c5` (Round 1, this repository).

What was fixed, where, and why
------------------------------

### WS-1 — Metadata recovery (`engine/driver.py`, `application/models.py`,
`application/conversion_service.py`, `cli/headless.py`)

The title chain gains a fourth, weakest-last tier; the author chain
gains a byline tier; language stops being a hardcoded guess.

1. **Title — filename evidence** (`_filename_title_candidate`). The
   Flower Garden's title exists only in the cover raster (verified:
   "The Flower Garden" appears nowhere in the text layer). The last
   deterministic witness is the file name, where such titles are
   usually written in caps: strip digit prefixes and trailing
   bracketed cruft, take the maximal *leading* run of fully-uppercase
   words (>= 2, <= 120 chars, digits inside tokens keep their shape —
   "COVID-19"), title-case it. Fires only when explicit, docinfo and
   first-page-heading evidence all failed. Lowercase or mixed file
   names keep the sentinel.
2. **Author — opening-pages byline** (`_first_pages_byline_candidate`).
   `By T. Albert` is a standalone 16 pt QikkiReg line on page 0. The
   harvest is anchored to lines *starting* with "By" (so "Published by
   Monkey Pen Ltd" and "Illustrated by: …" can never match), and the
   line must be typographically distinct from the body profile —
   smaller than the modal body size or in a different font family —
   so a title-case body sentence beginning "By The Time They Arrived"
   stays prose.
3. **Language — a real BCP-47 policy** (`_derive_language`). Explicit
   `--language` (well-formedness-validated, the same rule EPUBCheck
   applies; registry membership is not checkable without shipping a
   database) → the PDF catalog's `/Lang`, *also* validated — the
   Hands-On corpus book ships `/Lang` as `b'\xff5'`, which previously
   would have been silently dropped into a hardcoded `en` — → `und`,
   the honest "undetermined" tag. The `language="en"` default at the
   packaging seam is now `"und"`. A `--language` CLI flag threads the
   override through `ConversionRequest` into the engine.

### WS-2 — Evidence-gated cover designation (`engine/driver.py`,
`engine/packaging_and_validation.py`)

`cover-image` is assigned only when the title page *actually looks
like a cover*: an image on page 0 whose placement covers >= 90% of the
page, on a page carrying at most 200 characters of text (an
illustrated content page is dense with prose; a cover is not); the
largest qualifying placement wins. Anything weaker is a graceful
omission — EPUBCheck does not require the property, and a wrong
designation is worse than none. The chosen asset is added as an
`EpubCover` (the ebooklib item whose manifest entry carries
`properties="cover-image"`); no `cover.xhtml` page is invented, the
illustration is already page-0 content. Scanned books qualify
automatically: their vision-embedded page-0 rasters are full-bleed
with no text layer.

### WS-3 — Description-quality honesty (`engine/tier1_classifier.py`,
`engine/packaging_and_validation.py`)

`ImageElement` gains `alt_source` ("caption" | "location").
`AccessibilityProfile` counts `images_described` and
`images_location_only` separately; `alternativeText` is emitted only
when **every** content image carries a caption-derived description;
the summary states plainly what the descriptions are (including
"location-only" when they are stubs). The driver report line prints
`alt=described/total`.

The caption harvest itself was tightened by a finding this round's
accounting exposed on the real book: page 3's promotional art had
harvested the publisher's *Patreon donation plea* as its "caption" —
a pre-existing false positive, invisible until alt sources were
counted. Only caption-shaped text (`CAPTION_RE`: Figure/Table/Plate/
Chart/Image openings) is harvested now; a line that merely sits below
an image is never a description (no-fabrication rule).

### WS-4 — Packaging claims and the Ace gaps
(`engine/packaging_and_validation.py`)

1. **The WCAG conformance claim is removed** (decision: removal, not
   gating). The tool has never run a WCAG audit and EPUBCheck does not
   certify conformance; an unconditional "EPUB Accessibility 1.1 -
   WCAG 2.0 Level AA" `dcterms:conformsTo` misled readers and
   distributors. A regression test asserts no `conformsTo` ever
   appears.
2. **`xml:lang` on the `<package>` element** — the exact serious Ace
   violation (`epub-lang`) reproduced on three fixtures before the
   fix. ebooklib 0.20 hardcodes the package attributes, so
   `_set_package_xml_lang` rewrites the single OPF entry after the
   write: every other zip entry is copied byte-for-byte in original
   order, `mimetype` stays first and stored, and the swap is atomic
   (temp file + `os.replace`). A container-preservation test pins the
   zip invariants.
3. **nav.xhtml carries a real `<title>`** (the publication title);
   ebooklib's default empty title emitted no title element at all.

### WS-5 — Doctor: the four credential states
(`application/doctor.py`)

1. **State 1, env-var presence**, is now its own row per distinct
   credential variable (`env NVIDIA_API_KEY … set / not set`),
   independent of provider selection. This resolves the audit's
   PowerShell complaint: a user with `NVIDIA_API_KEY` exported but no
   provider selected previously saw only "no provider configured
   (offline)" — as if the key did not exist. Both facts are now
   separate lines.
2. **State 4, model completes a request**: an opt-in smoke check
   under the existing `--verify-credentials` flag (a real minimal
   completion through `create_llm_callable`; FAIL on failure or empty
   response, WARN when no model is selected). Doctor remains fully
   offline without the flag — no verification row, no smoke call.
   States 2 (provider selection) and 3 (credential validation) were
   already separate and are unchanged.

Verification evidence
---------------------

### Test suites

* Offline deterministic suite (EPUBCheck/Ace unresolvable,
  `NVIDIA_API_KEY` cleared, real-book env var set):
  **740 passed / 19 skipped / 0 failed**.
* Full validator-visible suite (EPUBCheck 5.1.0 **and** Ace 1.4.6
  resolvable, real-book integration on):
  **746 passed / 13 skipped / 0 failed**. The Round 1 record's three
  Ace-failing offline e2e tests pass; Ace reports 0 critical / 0
  serious everywhere it runs, including fixture output.
* New tests: **33** (14 publication-metadata, 8 packaging
  accessibility/cover, 4 driver-level cover selection, 1 caption
  no-fabrication, 5 doctor, 1 real-book integration gate), plus
  extended assertions in the CLI flag-mapping test and two packaging
  tests whose old expectations (the conformsTo claim; stub text
  counting as description) the Round 2 decisions supersede.

### Real-book gates (`tests/integration/test_flower_garden.py`, extended)

Fresh offline conversion of the source above:

* `dc:title` **The Flower Garden** (filename tier — the title is
  raster art), `dc:creator` **T. Albert** (byline tier),
  `dc:language` **en-GB** (PDF catalog `/Lang`).
* Cover property present on the title-page illustration
  (`img_91de749612417372.jpeg`); no `conformsTo`; package
  `xml:lang="en-GB"`; nav `<title>` non-empty.
* 35 media assets, 8 alpha-carrying PNGs, no 828x335 mask artifact,
  0 `<strong>` body lines, 0 false h4s — all Round 1 gates re-verified
  in the same run. Packaged `<p>` count **130, unchanged from Round 1**
  (no paragraph regressions; an earlier 118 figure in the session
  notes was a stream-level count, a different unit).
* **EPUBCheck: PASS, 0 errors. Ace: PASS, 0 critical / 0 serious /
  0 moderate / 0 minor** — Ace runs on the real book this round
  (Round 1 had to skip it).
* Output ~10.05 MB (unchanged image-size policy; Round 3 scope).

### Reference six-page book (`Artificial_Intelligence_Projects.pdf`,
SHA-256 `369B95FE20C4511B2BB29A6C3A66EE7FE561991273B5320DF65461544AA9638D`)

* Every frozen baseline metric is identical: chapters 1, headings 17,
  lists 11 (50 items), links 1, code 1, nav 17 / 0 unresolved, empty
  paragraphs 0; title "Artificial Intelligence" via the unchanged
  first-page-heading tier; author "Mohit Tripathi" via docinfo.
* Language now reads `en` *from the catalog `/Lang`* — the same value
  the old default guessed, but evidenced this time.
* Cover property correctly **omitted** (page 0 has no full-bleed
  image) and `alternativeText` correctly **not claimed** (the one
  image is a vision-page raster with a location-only note; Round 1
  output claimed the feature for it).
* EPUBCheck PASS 0 errors; **Ace PASS 0/0/0/0**.

### Corpus language-policy spot check (offline, structural-only)

| Document | /Lang evidence | dc:language out |
|---|---|---|
| Hands-On Generative AI (419 pp) | junk (`ÿ5`) | **und** (was a silent `en` lie) |
| LinuxNotesForProfessionals | absent | **und** |
| PRIYANSHU TRANSFIMER | `en-US` | **en-US** (title unchanged: "Term-Work", first-page-heading tier) |
| The Writing Habit | `en` | **en** (docinfo title unchanged) |

The pre-existing soft-mask warnings on the Hands-On book are the
Round 1 graceful-degradation path (opaque base kept, diagnostic
logged); unchanged by this round.

### Provenance pin

The repository-root artifact
`20250926124047041_THE_FLOWER_GARDEN_Free_Childrens_Book_By_Monkey.epub`
is the **pre-Round-1 BEFORE artifact** the audit examined — verified,
not assumed: SHA-256
`CD0DED00710F16C3B1C240E534A3F0A9FD7A2F0D7D8EC07256DAD78831C76429`,
containing 39 media assets, "Untitled Publication", "Unknown Author",
hardcoded `en`, the WCAG-AA conformsTo claim, no cover designation,
191 `<strong>` body lines and the ten false h4s. It is retained as
the historical BEFORE evidence for both rounds.

Before/after (real book)
-----------------------

| metric | BEFORE (pre-Round-1 artifact) | Round 1 | Round 2 (fresh) |
|---|---|---|---|
| dc:title | Untitled Publication | Untitled Publication | **The Flower Garden** |
| dc:creator | Unknown Author | Unknown Author | **T. Albert** |
| dc:language | en (hardcoded) | en (hardcoded) | **en-GB** (evidenced) |
| package xml:lang | absent | absent | **en-GB** |
| cover-image property | absent | absent | **designated** |
| dcterms:conformsTo | WCAG AA claim | WCAG AA claim | **none** |
| alternativeText claim | claimed (stubs) | claimed (stubs) | **not claimed; summary honest** |
| media assets | 39 | 35 | 35 |
| 828x335 mask artifact | 1 | 0 | 0 |
| `<strong>` body lines | 191 | 0 | 0 |
| false h4s (page-24 class) | 10 | 0 | 0 |
| EPUBCheck | not run | PASS 0 errors | PASS 0 errors |
| Ace | not run | not run (skipped) | **PASS 0/0/0/0** |

Honest notes
------------

* `und` is deliberate: when no evidence exists, the publication says
  "undetermined" and reading systems pick their own fallback, instead
  of the tool pretending every book is English.
* The Round 1 record's mention of `document-title` and
  `empty-heading` Ace violations is **not reproducible** on current
  code with Ace 1.4.6: the three-fixture reproduction showed exactly
  one serious violation (`epub-lang`) per fixture, now fixed. The
  validator-visible full suite (Ace running in every
  default-validator conversion) is the standing evidence; if those
  checks resurface on another fixture, they enter through the same
  session protocol.
* The cover policy is strictly page-0: a full-bleed frontispiece on a
  later page is not designated, and a dense illustrated first page is
  not a cover.
* The byline's distinctness guard uses the document font profile: a
  book whose byline is set at exactly body size in the body font will
  keep the author sentinel (conservative by design).
* EPUBCheck 5.1.0 accepts `dc:language`/`xml:lang` `und` with zero
  errors (verified on the LinuxNotes and Hands-On conversions).

Skipped checks (recorded, not claimed)
--------------------------------------

* **Live provider verification** (decision: offline-only this round) —
  digest pages verified through the deterministic fallback plus unit
  tests, as in Round 1.
* **Reader rendering screenshots** — unchanged deferral from Round 1.

Known limitations (unchanged, for later rounds)
-----------------------------------------------

1. Routing still has a single layout score (no separate visual
   confidence) — instrument-then-decide remains the agreed path.
2. Image-size policy (RGBA-PNG ~7x inflation, ~10 MB output) — Round 3
   by scope agreement.
3. `we re ready to open` — source-level ToUnicode defect (Round 1
   verification), untouched.
4. Digest-page furniture below the position-evidence guard, aligned
   tables as prose, chapter granularity/heading dedup — corpus-record
   dispositions unchanged.

Commands (reproducibility)
--------------------------

```
# offline deterministic suite (CI-like environment)
$env:NVIDIA_API_KEY = $null
$env:Path = <npm global bin removed>
.venv\Scripts\python.exe -m pytest

# real-book gates (both validators when installed)
$env:PDF2EPUB_FLOWER_PDF = <path to the Flower Garden PDF>
.venv\Scripts\python.exe -m pytest tests\integration

# doctor's four states
pdf2epub doctor                       # offline states only
pdf2epub doctor --verify-credentials  # adds remote validation + model smoke
```
