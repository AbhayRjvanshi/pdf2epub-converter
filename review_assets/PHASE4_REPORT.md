# Phase 4 — Rule A/B/C Comparison Against the 147-Image Verdict Set

Date: 2026-10-14
Source commit: `9708438` (Gate 2 closure)
Scope: evaluation only. No thresholds finalized, no production code changed, no RULES.md edits.

## 1. Reproducibility record

| Datum | Value |
|---|---|
| Source commit | `9708438` on `review/m3b-images` (Gate 2 closure) |
| Verdict manifest | `phase4_manifest.json` (147 entries, machine-readable, session artifact) |
| Rules source | `review_assets/RULES.md` at the same commit |
| Feature extraction | Downsample to ≤128 px max side (PyMuPDF `Pixmap.shrink`, power-of-2 halving); count over adjacent horizontal pixel pairs in downsampled RGB: `flat` (diff == 0), `crisp` (diff > 24/255), `micro` (0 < diff ≤ 24/255), `colors` (unique RGB tuples) |
| Toolchain | PyMuPDF 1.28.2, Python 3.10 (.venv), Windows 10 |
| Alpha | 0 of 147 sources carry alpha (all opaque JPX extractions); the shared alpha-lossless rule does not affect this set |
| Results artifact | `phase4_results.json` (session artifact) |

## 2. Rule C ambiguity resolution (documented before computation)

The RULES.md draft for Rule C specifies "10% borderline routing" without
an exact definition. The following was resolved and recorded before any
computation; it is a proposed interpretation, not an approved policy:

- Threshold pair: micro ≥ 0.25, colors ≥ 2000
- Borderline regions (relative distance): micro in [0.225, 0.275), colors in [1800, 2200)
- Line-art threshold: flat ≥ 0.35; borderline [0.315, 0.385)
- Photographic (outside all borderlines): micro ≥ 0.275 AND colors ≥ 2200 AND flat < 0.315
- Line-art (outside borderline): flat ≥ 0.385
- Precedence: line-art checked first; if flat ≥ 0.315 the image cannot be photographic
- Equality at outer boundaries (0.275, 2200, 0.385) = photographic/line-art (outside borderline)
- Equality at inner boundaries (0.225, 1800, 0.315) = uncertain (inside borderline)
- Any value in a borderline region → uncertain (conservative routing)

**Unresolved ambiguity**: whether the 10% distance should be relative to
the threshold itself (as defined above) or to the value's distance from
zero. The definition above uses relative-to-threshold (the standard
interpretation). This choice does not affect the conclusion, because
Rule C produces zero true approvals under either interpretation.

## 3. Comparison table

Ground truth: **21 JPEG-ELIGIBLE** (positive) + **126 LOSSLESS** (negative) = **147**

| Metric | Rule A (crispness-disjunct) | Rule B (micro-only) | Rule C (conservative borderline) |
|---|---|---|---|
| True approvals | 21 | **0** | **0** |
| **False approvals** | **109** | **80** | **31** |
| Missed opportunities | 0 | **21** | **21** |
| Correct rejections | 17 | 46 | 95 |
| Confusion total | 147 ✓ | 147 ✓ | 147 ✓ |
| Precision | 0.162 | **0.000** | **0.000** |
| Recall | 1.000 | **0.000** | **0.000** |
| Accuracy | 0.259 | 0.313 | 0.646 |

## 4. Per-image error analysis

### The fundamental finding

**All 21 human-approved JPEG-eligible photographs have very low
micro-texture (0.0001–0.154) and very high crisp-edge share (0.83–1.0).**
They are smooth photographs with clean boundaries — portraits, wildlife,
food, landscapes — not micro-textured images. Meanwhile, the images with
HIGH micro-texture (0.25–0.75) are predominantly spectrograms, gradient
diagrams, anti-aliased charts, and noise-pattern comparisons that the
review classified as LOSSLESS.

The features were designed under the assumption that "photographic =
high micro-texture." The evidence refutes this assumption for the images
in this corpus. The feature space does not contain a separating
boundary for this classification task.

### Rule A — 109 false approvals

Rule A's crispness disjunct (flat ≤ 0.01 AND crisp ≥ 0.80) captures
ALL 21 approved photographs — because they are all smooth with crisp
edges. But it also captures 109 LOSSLESS images with the same
signature: diagrams with sharp text on white backgrounds, spectrograms
with dense detail, charts with anti-aliased axes. The feature
combination "low flat + high crisp" means "no large uniform areas +
lots of sharp edges" — which describes BOTH photographs and
text-bearing diagrams equally well.

Notable false approvals include: Image 009 (watercolor flower
illustration, crisp=0.98), Image 024 (stylized flower painting,
crisp=1.0), Image 047 (leaderboard screenshot, micro=0.75), Image 073
(duck with depth map, crisp=0.999), Image 128 (UI screenshot,
micro=0.71).

### Rule B — zero true approvals, 80 false approvals

Rule B's micro ≥ 0.25 threshold captures NONE of the 21 approved
photographs (all have micro < 0.155) while still capturing 80 LOSSLESS
images (anti-aliased diagrams, spectrograms, gradient charts with
micro > 0.25). The rule is worse than useless: it misses every
legitimate photograph while still approving the wrong images.

### Rule C — zero true approvals, 31 false approvals

Rule C's combined micro ≥ 0.275 AND colors ≥ 2200 is more restrictive
than Rule B, reducing false approvals to 31 — but it still produces
ZERO true approvals because none of the approved photographs meet the
micro threshold. The color threshold does not help: the approved
photographs have colors from 1,601 to 14,067, overlapping fully with
the false-approval range.

### Individual false-approval review (Rule C, the most conservative)

Each of Rule C's 31 false approvals is an image the reviewer
classified as LOSSLESS for specific content reasons. The 5 largest
byte-cost false approvals:

1. Image 002 (xref 467, butterfly/noise-pattern panels) — micro 0.285,
   colors 4,915: high micro from the noise panels; the classifier sees
   texture, the reviewer sees scientifically meaningful noise patterns.
2. Image 017 (xref 432, butterfly reference grid) — micro 0.420: the
   same pattern — fine biological detail reads as "texture."
3. Image 044 (xref 193, dense model-family diagram) — micro 0.447,
   colors 3,437: anti-aliased diagram text and colored nodes create
   micro-differences.
4. Image 050 (xref 342, multicolored scatter plot) — micro 0.372:
   individual plotted points at varying colors create micro-texture.
5. Image 104 (xref 199, model-training resource diagram) — micro 0.540:
   gradient-filled diagram blocks read as photographic texture.

No feature-based adjustment can fix this: the same feature signatures
describe both JPEG-eligible photographs and lossless-required diagrams.

## 5. Phase 5 recommendation

**No feature-based rule (A, B, or C) is supported by the evidence for
production use.**

The 147-image verdict set demonstrates that the four deterministic
features (micro, flat, crisp, colors) cannot reliably separate
JPEG-eligible photographs from lossless-required content in real
documents. Every rule either produces massive false approvals (Rule A:
109 of 126 lossless images wrongly eligible) or misses every approved
photograph while still producing false approvals (Rules B and C: 0 true
approvals, 31–80 false approvals).

The specific reason: the human review relied on **content
understanding** — recognizing that an image is a photograph vs. a
diagram, spectrogram, or chart — which these features cannot capture.
Smooth photographs and sharp-edged diagrams share the same feature
signatures in this corpus.

**Proposed Phase 5 disposition:**

1. **Keep the transcode path lossless by default.** No deterministic
   feature-based classifier is validated for automatic JPEG selection
   on embedded-image transcoding.

2. **Record the 21 approved images as a human-curated set** for this
   specific document. If per-document savings are justified, the
   conversion can accept an explicit per-image or per-document
   override — but no automatic rule.

3. **M3a's measured-eligibility approach (encode both, keep the
   smaller) remains separate and unchanged.** That approach governs
   vision-embedded page rasters (scanned pages), where the content is
   known to be a photographic page render. It does not extend to the
   transcode path without its own validated quality gate.

4. **Any future lossy transcode policy requires either:**
   - A content-classification capability beyond the four features
     evaluated here (potentially including OCR text detection as a
     negative signal, edge-structure analysis, or a validated ML
     model — none currently in scope), **or**
   - A human-review workflow per document (as demonstrated in this
     round), **or**
   - Explicit user configuration per document.

**The projected 17.6% transcoded-class saving is withdrawn as a
near-term implementation target.** The 21 approved candidates' savings
(9,616,079 → 1,283,171 bytes) are achievable only through a mechanism
that no validated automatic rule currently supports. The honest
near-term result for the transcode path is: **no lossy encoding;
the 47.86 MB stays as lossless PNG.**

## 6. Gate status

Phase 4 is complete: the rules were evaluated against the complete
147-image ground truth, the comparison is reproducible from the
recorded artifacts, and the conclusion is documented. The gate
requires your review of this report before Phase 5 proceeds.
