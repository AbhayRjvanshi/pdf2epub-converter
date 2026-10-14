# The three candidate encoding rules ? ALL REJECTED FOR PRODUCTION

**Phase 4 verdict (2026-10-14): all three rules are refuted by the
147-image evidence set and are prohibited from authorizing production
JPEG transcoding.** See [PHASE4_REPORT.md](PHASE4_REPORT.md) for the
full comparison and [M3B_POLICY.md](M3B_POLICY.md) for the approved
lossless-by-default policy. The rules below are retained as historical
evidence so future work does not repeat the experiment without new
evidence.

These are the exact rule definitions as measured against the 180-source Hands-On feature set in this round ? recorded here so Phase 4 compares documented rules, not reinvented ones. All features are computed deterministically on a downsampled (<=128 px) RGB pixmap: 
**micro** = share of adjacent horizontal pixel pairs with per-channel max difference in (0, 24]; 
**crisp** = share with difference > 24; **flat** = share with difference == 0; 
**colors** = unique RGB tuples in the downsampled image.

## Rule A ? crispness-disjunct (the withdrawn permissive draft)

- photographic: `micro >= 0.25 OR (flat <= 0.01 AND crisp >= 0.80)`
- line-art: `flat >= 0.35`
- uncertain (lossless): everything else

Measured: classified 163/180 of the transcoded sources as photographic; the OCR pre-screen found 111 of those contain detected text ? this rule is refuted as a JPEG-approval signal by the review evidence and is retained for comparison only.

## Rule B ? micro-texture-only

- photographic: `micro >= 0.25`
- line-art: `flat >= 0.35`
- uncertain (lossless): everything else

Measured: classified 11/180 as photographic in the first pass draft. Maximum conservatism within the three-feature vocabulary; review outcomes may show it misses approved photographs.

## Rule C ? conservative borderline routing

- photographic: `micro >= 0.25 AND colors >= 2000` with borderline hysteresis: values within 10% of either threshold route to uncertain (lossless)
- line-art: `flat >= 0.35` (values within 10% route to uncertain)
- uncertain (lossless): everything else

Variant drafted during threshold pinning; its exact borderline margin and color floor are to be finalized in Phase 4 against the complete 147-verdict evidence set.

**All three rules share**: only the photographic class is JPEG-*eligible*; encoding still requires the measured size gate (JPEG only when smaller than PNG) and the fidelity gates; line-art and uncertain are always lossless; alpha-bearing rasters always lossless.