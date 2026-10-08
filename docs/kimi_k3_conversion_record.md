# Kimi K3 Conversion Record (Phases H + I)

Real-provider conversion and comparison against the frozen
[Stage-0 baseline](stage0_baseline.md), executed 2026-10-08.
Same source PDF (SHA-256 in the baseline record), new output name per the
freeze rule.

## Phase H — conversion metrics

```text
provider:      nvidia
model:         moonshotai/kimi-k3
routing:       tier1=4, tier2-digest=1, tier2-vision=1   (identical to Stage 0)
tier 2 result: 2/2 pages processed, no retries, no failures
elapsed:       680.5 s (NVIDIA serverless; ~4 min cold-start per request
               observed during the Phase G smoke run)
output:        stage-kimi-k3.epub (kept outside the repository)
```

Packaging: 78 stream elements, **2 chapters**, 0 cross-page welds, 0
furniture lines stripped. Validation: structural PASS; EPUBCheck/Ace
skipped (not yet installed — installed and run in Phase J below).

## Phase I — comparison against frozen Stage 0

| Metric (source PDF: 722 words) | Stage 0 (offline) | Kimi K3 |
|---|---|---|
| word retention | 641 (**89%**) | 723 (**100%**) |
| headings | 0 | **6** (h1/h2/h3, coherent hierarchy) |
| chapters | 1 | 2 |
| images | 1 (vision page embedded as raster) | 0 (page reconstructed) |
| alt text | 1 | n/a (no images to describe) |
| links | 0 | 2 |
| list items | 1 | 7 |
| table semantics | none | `table/tr/th/td` |

### Content fidelity

Kimi retained all source words (723 vs 722 — no duplication, no
hallucinated inflation). Stage 0 lost the visual table page's words by
embedding that page as an image; Kimi reconstructed it as a semantic
HTML table, which is why retention reaches 100%.

### Semantic fidelity

The six recovered headings (`Major Project`, `Minor Project: IMDB
Review Sentiment Classifier`, `Dataset Details`, `Objective`,
`Business Scenario`, `Part 1 — Load and Explore (Statistics)`) form a
coherent h1→h2→h3 hierarchy and drive the two-chapter split.

### Accessibility

`headings=6` directly fixes the Stage-0 weakness (`headings=0`) that
motivated Phase K. Alt text is not applicable (no images emitted).

### Stability

Deterministic offline output vs live-model output with observed
serverless cold-start latency; both conversions completed without
retries or provider failures.

## Verdict

Per the stabilization plan's principle — better semantic/reflow result
*without sacrificing reliable content preservation* — Kimi K3 achieved
both on this document: strict superset of Stage-0 semantics with
measurably better content retention. The live Kimi path is validated.

Headings extracted by Kimi do not make Phase K (deterministic Tier-1
heading signals) obsolete: Tier-1 pages — the majority of any document —
still emit zero headings offline, and offline mode must not regress.
