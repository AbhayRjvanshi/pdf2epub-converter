# M3b visual review ? Hands-On photographic-classified sources

## Review status (updated 2026-10-14 ? Gate 1 closed)

| Group | Count | Verdicts |
|---|---|---|
| Image 001?036 (OCR-negative) | 36 | **18 JPEG-ELIGIBLE ? 18 LOSSLESS** ? no UNCERTAIN, no PENDING |
| Image 037?147 (OCR-positive) | 111 | PENDING ? policy default UNCERTAIN/lossless |

**Measured projection from the 18 approved candidates only** (LOSSLESS and UNCERTAIN savings are never banked):
- 18 approved candidates: 8,219,873 ? 1,069,150 bytes (87.0% on the approved set)
- transcoded class projection if nothing else changes: 47,236,892 ? 40,086,169 bytes (15.1% on the class) ? provisional, pending the 037?147 review, rule comparison, and production benchmark

Verdict vocabulary: **LOSSLESS** ? PNG ? **UNCERTAIN** ? PNG ? **JPEG-ELIGIBLE** ? JPEG may be considered, subject to size and quality gates ? **PENDING** ? no lossy encoding.
JPEG-ELIGIBLE verdicts are provisional visual approvals, not guarantees of native-resolution perceptual equivalence; the difference maps are diagnostic aids only. Production encoding remains unauthorized.

- [REVIEW_1 ? 001?018](REVIEW_1.md) ? [REVIEW_2 ? 019?036](REVIEW_2.md) ? [REVIEW_3 ? 037?064](REVIEW_3.md) ? [REVIEW_4 ? 065?147](REVIEW_4.md)
- [COMPARISONS ? JPEG q90 test copies and amplified difference maps](comparisons/COMPARISONS.md)
- [RULES ? the three candidate encoding rules, exactly as measured](RULES.md)

OCR evidence: rapidocr-onnxruntime 1.4.4 / onnxruntime 1.23.2, confidence filter >= 0.5, 147/147 processed, runtime 1402 s, results JSON SHA-256 `1ed2d258143934b33d4403767812a4e22a1b3bf59f562a9aae9a412ab9048cd2`. OCR is a prioritization and exclusion signal, not proof of JPEG safety.