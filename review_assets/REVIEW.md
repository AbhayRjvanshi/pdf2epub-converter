# M3b visual review ? Hands-On photographic-classified sources

**36 OCR-negative images (Image 001?036) ? LIVE decisions, pending your review.**
**111 OCR-positive images (Image 037?147) ? UNCERTAIN/lossless by the conservative default policy; confirm or record a reconsideration.**

Report verdicts by xref (or image number). Available verdicts:

| Verdict | Meaning | Encoding outcome |
|---|---|---|
| LOSSLESS | text, fine detail, or other risk present | PNG |
| UNCERTAIN | evidence inconclusive | PNG |
| JPEG-ELIGIBLE | reviewed and accepted under the pinned policy | JPEG may be considered, subject to size and quality gates |
| PENDING | not yet reviewed | no lossy encoding |

All 147 entries default to **PENDING**. Thresholds remain provisional until these verdicts pin them.
The 73.4% size-reduction projection computed from the withdrawn permissive rule is void; the conservative projection after OCR-based exclusions is ~27.7% on the transcoded class and is itself still pending this review.

- [REVIEW_1 ? pending 001?018](REVIEW_1.md) ? [REVIEW_2 ? pending 019?036](REVIEW_2.md) ? [REVIEW_3 ? flagged 037?064](REVIEW_3.md) ? [REVIEW_4 ? flagged 065?147](REVIEW_4.md)

OCR evidence: rapidocr-onnxruntime 1.4.4 / onnxruntime 1.23.2, confidence filter >= 0.5, 147/147 processed, runtime 1402 s, results JSON SHA-256 `1ed2d258143934b33d4403767812a4e22a1b3bf59f562a9aae9a412ab9048cd2`. OCR is a prioritization and exclusion signal, not proof of JPEG safety.