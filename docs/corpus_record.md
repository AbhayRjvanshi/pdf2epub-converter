# Real-World Corpus Session — Record 1 (2026-10-10)

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
| Hands-On Generative AI (Sanseviero et al.) | B technical book | 419 | FAIL — 298 errors | FAIL — JPEG 2000 images (triaged) |
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

## Finding 3 (TRIAGED, not fixed): non-core image formats

**Failure class:** *JPEG 2000 (`.jpx`) images packaged with the wrong
media type.* The Hands-On book embeds 149 JPX images;
`MIME_BY_EXT.get(ext, "image/png")` labels every unknown extension as
`image/png`, so the OPF misdeclares them — and even correctly-labeled
JPX is not an EPUB 3 core media type. Proposed scoped fix (separate
task): transcode non-core rasters to PNG at extraction via
`fitz.Pixmap`, or detect the codestream magic and set the true media
type plus a core-format fallback. Not fixed in this session: it is a
new capability (image transcoding), not a defect in an implemented
fix, and the corpus protocol is record-then-triage.

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
