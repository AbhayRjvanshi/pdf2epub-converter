# Real-World Corpus Session — Record 1 (2026-10-10)

## Session 2 — scanned and multi-column classes (2026-10-10, after `c73a4c4`)

Six documents (three scanned, three multi-column), per the
regression-isolation protocol: source SHA-256, offline conversion with
defaults, routing, metrics, EPUBCheck per artifact. **All six pass
EPUBCheck cleanly; no new defects were confirmed.** No application
code changed in this session.

| Document | Class | Pages | Routing (t1/dig/vis) | Chapters | Headings | Images | EPUBCheck | Size |
|---|---|---|---|---|---|---|---|---|
| Play, dance & Music therapies (compressed) | C scanned (no text layer) | 74 | 0/0/74 | 1 | 0 | 74/alt | PASS 0 errors | 86.8 MB |
| COVID-19 Pediatrics paper | C scanned (sparse text, image-rich) | 24 | 0/24/0 | 40 | 60 | 553/alt | PASS | 1.5 MB |
| Microprocessor syllabus | C scanned (no text layer) | 2 | 0/0/2 | 1 | 0 | 2/alt | PASS | 0.7 MB |
| The Writing Habit | G multi-column booklet | 8 | 3/5/0 | 2 | 16 | 0 | PASS | <0.1 MB |
| UI Design Study Plan | G multi-column | 7 | 2/5/0 | 1 | 24 | 0 | PASS | <0.1 MB |
| Optimizer Modules Overview | G multi-column report | 11 | 10/1/0 | 13 | 78 | 0 | PASS | <0.1 MB |

Source SHA-256 (identity for reproduction): C1 `d00068d2f6f2d4e2…`,
C2 `881316eaea238a50…`, C3 `265336562d9845ac…`,
G1 `a60b97a94f0e5ac6…`, G2 `8183a6356146975c…`,
G3 `3c9a6900bb41c891…` (full hashes in the session artifacts).

### Scanned-class findings

- **Missing text is source-inherent, recorded separately from
  structural errors.** C1 and C3 have **no text layer at all** (0
  source characters); every page routes to vision and is embedded as a
  raster. The offline deterministic path performs no OCR — that is the
  documented tier policy, not a conversion defect. C2 carries sparse
  born-digital text (~380 chars/page) with 553 embedded images; its
  digest-routed pages render as coherent prose, EPUBCheck clean.
- **Observation (not a defect):** C1's output is **86.8 MB** — 74
  full-page scans re-encoded as PNG at ~1.2 MB each, ~7× the source's
  JPEG-compressed bytes. Photographic scans as PNG inflate size; a
  future enhancement could embed photographic rasters as JPEG.
  Mechanism inspected (all 74 are genuine PNG); triaged as a size
  optimization, not a correctness issue.

### Multi-column-class findings

- **Reading order is coherent.** Spot-checked extracted prose from G1
  and G2 chapters: flowing paragraphs in correct sequence, no column
  interleaving, no mid-sentence splits. The digest fallback's
  column-aware sort (evidence-gated since `a3cd742`) held on real
  multi-column layouts.
- **Observation:** G1 renders its title twice (cover-page label and
  in-content H1 both survive as separate headings) — the plan's
  "duplicate headings" nav edge case, visible here in content rather
  than navigation. EPUBCheck unaffected; recorded as evidence for any
  future heading-dedup pass.
- **Observation:** G3 yields 13 chapters / 78 headings from 11 pages —
  heading-granularity again behaving per the majors-only policy on
  section-dense documents, consistent with the Q&A-book observation
  from session 1.

### Session verdict

Two previously-untested document classes now have recorded evidence:
scanned documents convert to valid, EPUBCheck-clean image-preserving
EPUBs (with OCR explicitly out of deterministic scope), and
multi-column documents preserve reading order. Corpus coverage is now
**7 of 10 classes** (A, B, C, D, F, G-partial, I, J). Remaining gaps:
true magazine layouts with interleaved furniture. These results extend
the evidence base; they are not a broad reliability claim.

---

First measurement of the converter on real-world documents (Phase Q of
the post-conversion plan), run after the program closure (`68a5b39`).
Eight documents across five of the plan's ten classes; every document
is a real PDF from this machine, converted fully offline
(`--provider none` semantics), EPUBCheck 5.1.0 invoked per artifact.

## Corpus and results

| Document | Class | Pages | Result (pre-session) | Result (post-fixes) |
|---|---|---|---|---|
| PythonNotesForProfessionals | A text-heavy / H long | 856 | FAIL — EPUBCheck: unknown elements from raw `<…>` text | **PASS** — 0/0/0/0, 110 s |
| LinuxNotesForProfessionals | A text-heavy | 65 | FAIL — same leak | **PASS** |
| Hands-On Generative AI (Sanseviero et al.) | B technical book | 419 | FAIL — 298 errors | **PASS** — EPUBCheck 0/0/0/0, 29 s (post-JPX fix) |
| PRIYANSHU TRANSFIMER | F academic (image-heavy) | 22 | PASS | PASS |
| Compiler Design Synopsis | F2 report | 19 | PASS | PASS |
| OS course notes | D tables/course | 16 | PASS | PASS |
| DBMS course notes | D2 tables/course | 17 | PASS | PASS |
| THE FLOWER GARDEN (children's) | I decorative/curved + J mixed | 32 | PASS | PASS |

Classes not yet covered: C scanned (no scanned non-personal document
was available on this machine), E magazine-style, G long-form magazine
layouts. **This session is partial coverage, not proof of broad
reliability** — exactly the distinction the closure record demands.

## Finding 1 (FIXED): lxml decode → stream seam escaping

**Failure class:** *entity-decoded text violates the escaped-content
contract at the Tier-2 stream seam.* All three book failures shared
one root cause: `_digest_fallback` emits correctly-escaped
`<your_command>`, lxml **decodes** the entity on parse, and
`parse_xhtml_to_stream_elements` copied `element.text` /
`text_content()` — raw `<` — straight into `StreamElement.content`.
Chapter bodies then contained live unknown elements
(`<your_command>`, `<section>`, `<ip_rem>`) that EPUBCheck rejects; in
one chapter a leaked Django-template `<ul>` corrupted list structure.
No synthetic fixture ever crossed this seam, because fixtures exercise
Tier 1 and the digest render, not the lxml parse of fallback output.

Fix: `_inner_xhtml` and the flattening branch re-escape decoded text
(`driver.py`); three regression tests including the XML round-trip.

## Finding 2 (FIXED): markdown reference links poison linkify

**Failure class:** *markdown reference syntax glues `][N]` onto the
URL match.* Technical books quote markdown (`([url][1]`); the
linkify regex matched through the brackets and produced invalid
hrefs (`…html][1]`) that EPUBCheck rejects (RSC-020). Fix: a precise
`\]\[\d+\]$` suffix strip (bracket *balancing* was wrong — the opening
`[` sits outside the match), with IPv6-host and reference-suffix
regression tests.

## Finding 3 (FIXED, 2026-10-10): non-core image formats

**Failure class:** *JPEG 2000 (`.jpx`) images packaged with the wrong
media type.* The Hands-On book embeds 149 JPX images (all verified as
genuine JP2 signature-box data, not inferred from extensions);
`MIME_BY_EXT.get(ext, "image/png")` labelled every unknown extension
`image/png`, and JPX is not an EPUB 3 core media type in any case —
298 EPUBCheck errors.

Fix (scoped, per the review contract): `_transcode_to_core` in
`tier1_classifier` decodes any non-core raster (`jpx`/`jp2`/`j2k`,
BMP, TIFF, WebP) via PyMuPDF and re-encodes as PNG at extraction —
CMYK/indexed sources converted to RGB, alpha preserved, content hash
taken from the *packaged* bytes so dedup stays honest. **Failure
behavior:** an undecodable image is dropped with a logged diagnostic
naming page, block and format — never silently relabelled. Acceptance
was validated at every level: a committed 1.5 KB JP2 asset embedded
through a handcrafted `/JPXDecode` PDF (`jpx_image` fixture, provenance
documented), extraction-level tests for both the transcode and the
drop-with-diagnostic path, EPUBCheck 0/0/0/0 on the fixture EPUB, and
the full Hands-On book — **8/8 corpus documents now pass**, all 168
packaged images core-format with zero mislabelled files.

Guardrails after the fix: suite **681 passed / 14 skipped / 0 failed**
(679 + 2); six-page reference baseline byte-identical.

## Discrepancies observed but not triaged as defects

- **Chapter granularity on Q&A-style books:** 1206 chapters for 856
  pages — the majors-only policy is behaving as designed on real
  heading structure, but per-question chapter splitting may be finer
  than readers want. Evidence for a future chapter-granularity tuning
  discussion, not a failure.
- **`empty_paragraphs` metric vs structural check:** the A-long-book
  reported 3 stream-level empty paragraphs pre-fix while the
  packaged-output check found none (they are dropped at body
  preparation). Informational only.

## Verification

- Full suite after both fixes: **679 passed / 14 skipped / 0 failed**
  (674 + 5 new), exit 0.
- Six-page reference baseline: **unchanged** (chapters 1, headings 17,
  lists 11/50, links 1, code 1, nav 17/0, empty 0, EPUBCheck PASS).
- Corpus artifacts (uncommitted, in `%TEMP%\opencode\corpus*`):
  EPUBs, EPUBCheck logs, `summary.json`.
