# M3b Policy — Embedded-Image Transcode Behavior

Status: **Phase 5 policy — approved for documentation, not yet implemented**
Date: 2026-10-14
Evidence: [PHASE4_REPORT.md](PHASE4_REPORT.md) (all three rules rejected)
Scope: original embedded images extracted from PDFs and repackaged into EPUBs.
Does NOT govern the M3a page-raster path (vision-embedded scanned pages), which
has its own validated measured-eligibility approach and remains unchanged.

---

## Decision A — Default behavior

**Original embedded images remain lossless by default.**

When the converter extracts an embedded image (JPX, BMP, TIFF, WebP, or any
non-core source format) and repackages it into the EPUB, the output is the
lossless PNG transcoding currently in production. No automatic lossy
conversion may occur based on the four measured features (micro, flat,
crisp, colors) or any rule derived from them.

This is the rejection of an unsupported selection method, not a claim
that JPEG is inherently unsuitable for all embedded images. The current
automatic decision mechanism is not sufficiently reliable to choose
which images may be lossy-compressed.

## Decision B — Exception mechanism (deferred)

Three routes exist for future savings; **none is implemented now**:

1. **Human curation per document.** A reviewer identifies specific images
   and approves JPEG encoding for those images only. Requires a defined
   identity mechanism (see Test Plan, item 7) and per-conversion recording.
2. **A validated content classifier** that goes beyond the four features
   evaluated in Phase 4 — potentially including OCR text detection as a
   negative signal, edge-structure analysis, or a validated ML model.
3. **Explicit user configuration** per document or per conversion job.

Any exception workflow is a separate, explicitly approved feature. The
21 reviewed candidates are evidence of potential savings in one specific
document (the Hands-On corpus book) and must not become a global
allowlist. The reviewed image numbers are not stable identifiers
outside that corpus.

## Decision C — Encoding gates (for any future authorized exception)

An explicitly authorized image must pass ALL of these gates before
JPEG encoding is used:

1. **Alpha gate**: alpha-bearing images remain lossless. No exception.
2. **Size gate**: the JPEG candidate must be smaller than the lossless
   PNG output. The size baseline is the **packaged lossless PNG bytes**
   (the bytes the current pipeline would write into the EPUB), not the
   original source format's bytes.
3. **Fidelity gate**: a smaller JPEG is not sufficient. The approved
   fidelity criteria (from the M3a quality-protocol pattern: measured
   max/mean pixel difference plus the amplified difference-map review
   for any candidate whose quality is in question) must pass.
4. **Fallback**: if any gate fails or is indeterminate, the output
   remains lossless.

## Decision D — M3a separation

| Property | M3a (page-raster) | M3b (embedded images) |
|---|---|---|
| Input | Full-page raster render | Original embedded image |
| Content | Known page render | May be photo, diagram, chart, screenshot, mixed |
| Decision | Measured eligibility (encode both, keep smaller) | **Lossless by default** (this policy) |
| Change | **Unchanged** | This policy governs only this path |

M3a's success does not validate M3b's classifier; they solve different
problems. M3b's rejection does not disable M3a; they are separate code
paths.

## Decision E — What the enforcement tests must prove

These are the policy requirements the implementation-phase tests must
demonstrate before production code is merged. They are specifications,
not claims that tests currently exist.

1. **Default preservation**: an embedded image without explicit
   authorization is never lossy-transcoded.
2. **Classifier disabled**: Rules A, B, and C cannot independently
   authorize JPEG encoding.
3. **Alpha preservation**: alpha-bearing images remain lossless.
4. **Size fallback**: a JPEG candidate that is not smaller cannot
   replace the lossless output.
5. **Fidelity fallback**: a candidate that fails or cannot complete a
   fidelity check remains lossless.
6. **Exception isolation**: an approval for one image or job cannot
   silently authorize other images or future jobs.
7. **Stable identity**: a reviewed image is matched to the intended
   source by content hash or xref, not by dimensions alone.
8. **M3a regression**: existing page-raster optimization behavior
   remains unchanged.
9. **Packaging integrity**: the EPUB references the correct output
   images and remains valid (EPUBCheck, structural check) after any
   encoding change.

## What is explicitly prohibited

- Tuning thresholds on the four features in the hope of salvaging
  Rules A, B, or C as production classifiers.
- Claiming the withdrawn 17.6% projection is achievable automatically.
- Counting the 21 human-approved candidates as production savings.
- Implementing a JPEG encoder or a hidden fallback to lossy output
  under this policy.
- Altering M3a's page-raster optimization.
- Treating OCR detection alone as a complete content classifier.
- Changing `main` or production behavior while this policy is under
  review.

## Conditions to reopen the investigation

Any future lossy-transcode proposal must present:
1. A content-classification capability beyond the four evaluated
   features, with its own validation evidence against a real corpus.
2. Or a defined human-review workflow with stable image identity,
   approval scope, and recording requirements.
3. Or explicit per-document user configuration with the encoding
   gates of Decision C.

Without one of these, the transcode path remains lossless.
