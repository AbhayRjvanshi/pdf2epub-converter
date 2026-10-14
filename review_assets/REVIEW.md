# M3b visual review ? Hands-On photographic-classified sources

## Review status (updated 2026-10-14)

| Group | Count | Verdicts |
|---|---|---|
| Image 001?036 (OCR-negative) | 36 | **18 JPEG-ELIGIBLE ? 18 LOSSLESS** ? closed |
| Image 037?147 (OCR-positive) | 111 | **3 JPEG-ELIGIBLE ? 4 LOSSLESS** recorded (7 of 111 reviewed) ? **104 PENDING** (policy default UNCERTAIN/lossless) |

**Recorded JPEG-ELIGIBLE on OCR-positive images (048, 061, 062) are documented, reviewer-approved reconsiderations of the policy default, each with recorded rationale ? never silent overrides.**

**Measured projection from the 21 approved candidates only** (LOSSLESS/UNCERTAIN/PENDING savings are never banked):
- approved set: 9,616,079 ? 1,283,171 bytes (86.7% on the approved set)
- transcoded class projection if nothing else changes: 47,236,892 ? 38,903,984 bytes (17.6% on the class) ? provisional: 104 images remain PENDING

Verdict vocabulary: **LOSSLESS** ? PNG ? **UNCERTAIN** ? PNG ? **JPEG-ELIGIBLE** ? JPEG may be considered, subject to size and quality gates ? **PENDING** ? no lossy encoding. Production encoding remains unauthorized.

- [REVIEW_1 ? 001?018](REVIEW_1.md) ? [REVIEW_2 ? 019?036](REVIEW_2.md) ? [REVIEW_3 ? 037?064](REVIEW_3.md) ? [REVIEW_4 ? 065?147](REVIEW_4.md)
- [COMPARISONS ? 001?036 test pairs](comparisons/COMPARISONS.md)
- [Phase 2 batches ? 037?147 test pairs](comparisons/BATCH_037_147.md) ? [batch artifacts ZIP](comparisons/m3b_batch_artifacts.zip)
- [RULES ? the three candidate encoding rules](RULES.md)

OCR evidence: rapidocr-onnxruntime 1.4.4 / onnxruntime 1.23.2, confidence filter >= 0.5, 147/147 processed, runtime 1402 s, results JSON SHA-256 `1ed2d258143934b33d4403767812a4e22a1b3bf59f562a9aae9a412ab9048cd2`. OCR is a prioritization and exclusion signal, not proof of JPEG safety.