# M3b Final Record — Embedded-Image Transcode Investigation and Policy Decision

Date: 2026-10-14
Status: **Investigation complete; lossless-by-default policy in force;
no production encoder implemented; no production code changes required.**
Evidence branch: `review/m3b-images` (all review artifacts, verdicts,
comparisons, and policy documents)
Baseline commit on main: `d1f7415` at the time of investigation

---

## 1. What was investigated

The Round 3 plan (M3b) asked whether the converter could reduce EPUB
size by selectively JPEG-compressing original embedded images (the
~47.86 MB of JPX-to-PNG transcoded assets in the Hands-On corpus
document) without damaging content that the conservative policy
requires to remain lossless.

Three deterministic feature-based rules were proposed, using four
measured features (micro-texture, flat-run share, crisp-edge share,
unique colors) computed on a downsampled RGB pixmap:

- **Rule A** (crispness-disjunct): photographic if micro ≥ 0.25 OR
  (flat ≤ 0.01 AND crisp ≥ 0.80)
- **Rule B** (micro-only): photographic if micro ≥ 0.25
- **Rule C** (conservative borderline): photographic if micro ≥ 0.275
  AND colors ≥ 2200, with 10% borderline routing to uncertain

## 2. The 147-image evidence set

Every embedded-image source in the Hands-On corpus document was
inventoried (M0b, commit `5dd3135`), OCR-screened for text content
(RapidOCR, 147/147 processed), and visually reviewed by the project
maintainer with per-image verdicts, reasons, and review dates.

### OCR pre-screen

| Tool | Setting | Result |
|---|---|---|
| rapidocr-onnxruntime 1.4.4 / onnxruntime 1.23.2 | confidence ≥ 0.5 | **111 of 147** sources contain detected text (diagrams, charts, labels, leaderboards, spectrograms) |

OCR is a prioritization signal, never proof of JPEG safety or
unsuitability.

### Visual review

| Group | Count | JPEG-ELIGIBLE | LOSSLESS |
|---|---|---|---|
| Images 001–036 (OCR-negative) | 36 | 18 | 18 |
| Images 037–147 (OCR-positive) | 111 | 3* | 108 |
| **Total** | **147** | **21** | **126** |

*The 3 OCR-positive JPEG approvals (Images 048, 061, 062) are
documented, reviewer-approved reconsiderations of the OCR-positive
lossless default — exceptions, not a general precedent.

**Zero PENDING, zero UNCERTAIN, zero unresolved.** All 147 images
have explicit verdicts with recorded reasons.

### What the review established

The 147 images revealed that the Hands-On corpus is dominated by
technical diagrams, charts, spectrograms, token examples, mixed-
content model demonstrations, and embedded photographs with labels,
masks, or overlays. Pure photographs without mixed content are rare
(21 of 147, mostly in the OCR-negative group).

## 3. The rule comparison (Phase 4)

All three rules were evaluated against the complete 147-verdict ground
truth. The results are unambiguous:

| Metric | Rule A | Rule B | Rule C |
|---|---|---|---|
| True approvals | 21 | **0** | **0** |
| **False approvals** | **109** | **80** | **31** |
| Missed opportunities | 0 | **21** | **21** |
| Correct rejections | 17 | 46 | 95 |
| Precision | 0.162 | **0.000** | **0.000** |
| Recall | 1.000 | **0.000** | **0.000** |

**All three rules are rejected for production use.**

The root cause: all 21 approved photographs have low micro-texture
(0.0001–0.154) and high crisp-edge share (0.83–1.0) — smooth
photographs with clean boundaries — while the lossless-required
diagrams share the same feature signatures. The features cannot
distinguish "portrait photograph" from "diagram with sharp text on a
white background" in this corpus.

Full comparison: [PHASE4_REPORT.md](PHASE4_REPORT.md)

## 4. The policy decision (Phase 5)

**Original embedded images remain lossless by default.**

- No automatic JPEG transcoding is permitted based on the four
  measured features or any rule derived from them.
- Exception mechanisms (human curation, validated content classifier,
  explicit user configuration) are **deferred**, not implemented.
- Any future exception must pass alpha, size (vs packaged lossless
  PNG bytes), and fidelity gates.
- M3a's page-raster optimization is **separate and unchanged**.
- The 17.6% projected saving is **withdrawn** as an implementation
  target — no validated automatic rule supports it.

Full policy: [M3B_POLICY.md](M3B_POLICY.md)
Decision record: [PHASE5_DECISION.md](PHASE5_DECISION.md)

## 5. The test evidence (Phase 6)

Thirteen policy-enforcement tests were written against the unchanged
production code. **All 13 pass.** The current implementation already
satisfies the lossless-by-default policy:

- `_transcode_to_core` always produces PNG (hardcoded, no runtime
  override)
- No hidden lossy authorization path exists (verified by code
  inspection and grep across the entire engine)
- Core-format sources pass through byte-identical
- Decode failure drops with diagnostic, never a lossy fallback
- Content-hash dedup, not dimension dedup
- M3a's measured-eligibility approach confirmed unchanged

Full baseline: [PHASE6_BASELINE.md](PHASE6_BASELINE.md)

**No production code changes are required.** The policy is enforced
by the architecture itself; the tests are regression guards.

## 6. Projected vs. realized savings

| Figure | Status |
|---|---|
| 73.4% (47.86 → 12.74 MB) | **Withdrawn** — assumed all 19 tested candidates pass; based on the permissive Rule A which was subsequently refuted |
| 17.6% (47.24 → 38.90 MB) | **Withdrawn** — based on 21 approved candidates but no validated automatic rule exists to select them |
| 86.7% (on the approved set) | **Context only** — 21 human-curated candidates; not an automatic saving |
| **Realized M3b saving** | **0%** — the transcoded class remains lossless PNG (47.86 MB) |

The 21 curated images are evidence of potential savings under a
future human-review workflow. They are **not** a production
allowlist, and the reviewed image numbers are not stable identifiers
outside the Hands-On corpus.

## 7. What would justify reopening M3b

Any future lossy-transcode proposal must present one of:

1. **A validated content classifier** that goes beyond the four
   evaluated features (micro, flat, crisp, colors), with its own
   validation evidence against a real corpus — potentially including
   OCR text detection as a negative signal, edge-structure analysis,
   or a validated ML model.
2. **A properly scoped human-review workflow** with stable image
   identity (content hash or xref, not dimensions alone), defined
   approval scope (one image, one job, or all jobs for a source), and
   recording requirements.
3. **Explicit per-document user configuration** with the size and
   fidelity gates of the approved policy.

Without one of these, the embedded-image transcode path remains
lossless.

## 8. Round 3 M3b summary

| Aspect | Result |
|---|---|
| Question investigated | Can embedded images be safely JPEG-compressed? |
| Evidence | 147 images reviewed, 3 rules tested, OCR pre-screen, per-image verdicts |
| Answer | **No validated automatic rule exists to select eligible images** |
| Policy | **Lossless by default; no automatic lossy transcoding** |
| Production changes | **None required** — the current code already enforces the policy |
| Size impact | **0% on the M3b path** — the 47.86 MB stays as lossless PNG |
| M3a impact | **None** — page-raster optimization unchanged and independently successful (C1: −63.0%) |
| Tests | 13 policy-enforcement tests, all passing, committed as regression guards |
| Future | Reopen only with a validated classifier, human-review workflow, or explicit user configuration |
