# M3b visual review ? Hands-On photographic-classified sources

## Review status ? **GATE 2 CLOSED** (2026-10-14)

| Group | Count | Verdicts |
|---|---|---|
| Image 001?036 (OCR-negative) | 36 | **18 JPEG-ELIGIBLE ? 18 LOSSLESS** |
| Image 037?147 (OCR-positive) | 111 | **3 JPEG-ELIGIBLE (documented exceptions) ? 108 LOSSLESS** |
| **Total** | **147** | **21 JPEG-ELIGIBLE ? 126 LOSSLESS ? 0 PENDING ? 0 UNCERTAIN** |

**All 147 images have explicit verdicts. Gate 2 is closed.**

The 3 OCR-positive JPEG approvals (Images 048, 061, 062) are documented, reviewer-approved reconsiderations of the OCR-positive default ? each with recorded rationale. They are exceptions to the default, not proof that OCR-positive images are generally safe to transcode.

**Final approved-candidate set: 21 candidates** (LOSSLESS savings are never banked):
- approved set: 9,616,079 ? 1,283,171 bytes (86.7% on the approved set)
- transcoded class projection: 47,236,892 ? 38,903,984 bytes (17.6% on the class) ? this is the Phase 3 reconciled projection, not a realized saving; production encoding remains unauthorized

Verdict vocabulary: **LOSSLESS** ? PNG ? **UNCERTAIN** ? PNG ? **JPEG-ELIGIBLE** ? JPEG may be considered, subject to size and quality gates. Production encoding remains unauthorized until the policy, test, fidelity, and release gates pass.

- [REVIEW_1 ? 001?018](REVIEW_1.md) ? [REVIEW_2 ? 019?036](REVIEW_2.md) ? [REVIEW_3 ? 037?064](REVIEW_3.md) ? [REVIEW_4 ? 065?147](REVIEW_4.md)
- [COMPARISONS ? 001?036 test pairs](comparisons/COMPARISONS.md)
- [Phase 2 batches ? 037?147 test pairs](comparisons/BATCH_037_147.md)
- [Screening batch manifest](comparisons/SCREENING_BATCH.md) ? [screening ZIP](comparisons/m3b_screening_batch.zip)
- [RULES ? the three candidate encoding rules](RULES.md)

OCR evidence: rapidocr-onnxruntime 1.4.4 / onnxruntime 1.23.2, confidence filter >= 0.5, 147/147 processed, runtime 1402 s, results JSON SHA-256 `1ed2d258143934b33d4403767812a4e22a1b3bf59f562a9aae9a412ab9048cd2`. OCR is a prioritization and exclusion signal, not proof of JPEG safety.