# Phase 5 Decision Record — M3b Policy

Date: 2026-10-14
Reviewer: project maintainer (via conversation)
Evidence base: [PHASE4_REPORT.md](PHASE4_REPORT.md), [M3B_POLICY.md](M3B_POLICY.md)

---

## Approved decisions

| # | Decision | Status |
|---|---|---|
| A | Original embedded images remain **lossless by default** | Approved |
| B | Exception mechanism (human curation, validated classifier, user config) is **deferred** — not implemented | Approved |
| C | Any future exception must pass alpha, size (vs packaged lossless PNG bytes), and fidelity gates | Approved |
| D | M3a page-raster optimization is **separate and unchanged** | Approved |
| E | The nine enforcement-test requirements are documented as the implementation-phase contract | Approved |

## Rejected alternatives

| Alternative | Reason for rejection |
|---|---|
| Rule A (crispness-disjunct) as production classifier | 109 false approvals: 109 of 126 LOSSLESS images would be wrongly JPEG-eligible; precision 0.162 |
| Rule B (micro-only) as production classifier | Zero true approvals: misses all 21 approved photographs; still has 80 false approvals |
| Rule C (conservative borderline) as production classifier | Zero true approvals; still has 31 false approvals |
| Tuning thresholds on the same four features | The feature space does not contain a separating boundary for this classification task; adjustment cannot fix a fundamentally misaligned signal |
| The 17.6% projection as an implementation target | Withdrawn: no validated automatic rule supports it |
| The 21 approved candidates as production savings | They are evidence of potential savings under a human-curated workflow, not automatic savings |

## Unresolved questions (explicitly deferred)

1. **Exception workflow design**: if a human-review or per-document
   opt-in is later approved, the stable-identity mechanism (xref?
   content hash? both?) and the approval's scope (one conversion?
   all conversions of the same source?) must be specified precisely.
2. **Size-comparison baseline refinement**: the current baseline is
   the packaged lossless PNG bytes; a future alternative lossless
   format (e.g., WebP lossless) would require re-baselining.
3. **Fidelity criteria formalization**: the M3a pattern (max/mean
   pixel difference + amplified difference-map review) is the
   working method; a formal acceptance threshold has not been
   pinned for embedded-image transcoding because no authorized
   exceptions currently exist to apply it to.

## Consistency check (verified before policy finalized)

The Phase 4 confusion-matrix counts were independently verified against
the per-image manifest:
- 147 entries, 147 unique image numbers (001–147), zero duplicates
- 21 JPEG-ELIGIBLE + 126 LOSSLESS = 147; zero PENDING, zero UNCERTAIN
- Rule A: 21+109+0+17=147 ✓; Rule B: 0+80+21+46=147 ✓; Rule C: 0+31+21+95=147 ✓
- Every false approval verified as a LOSSLESS-verdict image in the manifest
- Every missed opportunity verified as a JPEG-ELIGIBLE-verdict image in the manifest
- All four feature values present for all 147 entries

## Sign-off

The Phase 4 finding (all three rules rejected) and the Phase 5 policy
(lossless-by-default, no automatic JPEG authorization by the rejected
rules, M3a unchanged, exceptions deferred) are approved by the project
maintainer as documented in this record. The next step is the
implementation-planning phase: the failing-first tests and fixtures
that enforce this policy, to be written before any production code
changes.

Production encoding remains unauthorized. `main` remains untouched.
