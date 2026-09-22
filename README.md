# Hybrid PDF → EPUB3 Converter

A two-tier PDF to EPUB3 pipeline. Clean pages are converted by a deterministic
layout engine at zero API cost; only the pages that genuinely defeat heuristics
are sent to a model. Output is a reflowable, chapter-segmented EPUB3 with
accessibility metadata that reflects what the file actually contains.

Verified on a 500-page book: **11.7 s wall, 95 MB peak RSS, EPUBCheck 5.1.0
clean (0 fatals / 0 errors / 0 warnings)**.

---

## Install

```bash
pip install -r requirements.txt

# Optional external validators
#   EPUBCheck  (Java)  https://github.com/w3c/epubcheck/releases
#   Ace by DAISY (Node) npm install -g @daisy/ace
```

Both validators are optional. When absent the pipeline says so and falls back
to its own structural checker rather than pretending to have validated.

## Use

```bash
# Offline: deterministic tier only, no API key needed
python main.py book.pdf -o book.epub --provider none

# With a model for the hard pages
export OPENAI_API_KEY=...
python main.py book.pdf -o book.epub --title "My Book" --author "A. Name"

export ANTHROPIC_API_KEY=...
python main.py book.pdf -o book.epub --provider anthropic --model claude-sonnet-4-5

# Inspect routing before spending anything
python main.py book.pdf --report-only
```

```
  page | score | target        | sigma | order | vectors | reason
  -----+-------+---------------+-------+-------+---------+-------------------
     1 |   100 | tier1         |  1.32 |     0 |       0 | clean
     5 |    80 | tier2-digest  |  0.46 |     1 |       0 | reading_order:-20
     6 |     0 | tier2-vision  |  0.00 |     0 |       0 | sanity:no_text_layer
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `-o, --output` | `output.epub` | output path (directories created) |
| `--title`, `--author` | from PDF metadata | override publication metadata |
| `--provider` | `openai` | `openai`, `anthropic`, or `none` |
| `--model` | `gpt-4o` | model id for Tier 2 |
| `--batch-size` | `4` | pages per Tier 2 request |
| `--cache-dir` | `.cache_llm_epub` | composite-keyed response cache |
| `--max-repair-attempts` | `2` | validation → repair iterations |
| `--font-sample-pages` | `160` | pages sampled for the typography baseline |
| `--no-spool-images` | off | keep extracted images in RAM |
| `--report-only` | off | print the routing table and exit |
| `--skip-validation` | off | skip the validation gate |

Exit codes: `0` success, `1` conversion or validation failure, `2` bad input.

---

## Architecture

```
                         ┌──────────────┐
                         │  Input PDF   │
                         └──────┬───────┘
                                ▼
                  ┌─────────────────────────┐
                  │ Global font profiling   │  sampled, not exhaustive
                  └─────────────┬───────────┘
                                ▼
                  ┌─────────────────────────┐
                  │  Confidence router      │  one extraction per page
                  │  sanity → score → route │  payloads built lazily
                  └─────────────┬───────────┘
                 ┌──────────────┴──────────────┐
          score ≥ 85                      score < 85
                 ▼                              ▼
     ┌───────────────────────┐    ┌──────────────────────────┐
     │ Tier 1  deterministic │    │ Tier 2  digest or vision │
     │ PyMuPDF, $0           │    │ JSONL bbox / 150 DPI PNG │
     └───────────┬───────────┘    └────────────┬─────────────┘
                 └──────────────┬──────────────┘
                                ▼
                  ┌─────────────────────────┐
                  │ Unified element stream  │  one list for the whole book
                  └─────────────┬───────────┘
                                ▼
                  ┌─────────────────────────┐
                  │ Reassembly & packaging  │  furniture strip, page-seam
                  │                         │  weld, chapter segmentation
                  └─────────────┬───────────┘
                                ▼
                  ┌─────────────────────────┐
                  │ Validation & self-repair│  internal + EPUBCheck + Ace
                  └─────────────────────────┘
```

The stream is the design decision that matters. Page boundaries are not file
boundaries, so a paragraph straddling pages 42–43 is welded back together, a
running header is detected across the whole book, and chapter files are cut at
heading nodes rather than at page numbers.

### Modules

| File | Responsibility |
|---|---|
| `tier1_classifier.py` | Font profiling, span styling, paragraph unwrapping, code blocks, image extraction → `StreamElement` |
| `confidence_router.py` | Text-sanity gate, layout scoring, asymmetric routing, payload construction |
| `tier2_llm_handler.py` | Dual-path model calls, composite caching, batch integrity, XHTML repair gate |
| `packaging_and_validation.py` | Furniture stripping, cross-page welding, chapter segmentation, honest a11y metadata, validator parsing |
| `main.py` | Orchestration, API adapters, self-repair loop, CLI |

---

## Routing

A page is scored 0–100 and routed at 85. The threshold is deliberately strict
because the two error directions do not cost the same:

| Outcome | Reality | Action | Cost |
|---|---|---|---|
| True negative | simple page | Tier 1 | $0, correct |
| True positive | complex page | Tier 2 | ~$0.002 |
| **False positive** | simple page | Tier 2 | ~$0.002 wasted |
| **False negative** | complex page | Tier 1 | silent corruption, false a11y claims |

| Signal | Threshold | Penalty |
|---|---|---|
| Weighted font σ | > 3.5 pt | `min(35, (σ − 3.5) × 12)` |
| Reading-order violations | > 0 | `min(45, n × 20)` |
| Vector path density | > 20 | `min(30, (n − 20) × 1.5)` |

Reading-order violations are counted over body content only. Running headers
and footers are usually emitted before or after the body blocks, which would
otherwise register one enormous backward jump on every page of a normal book
and push an entire clean publication onto the paid tier.

The sanity gate runs first: no text layer, >15 % private-use/control
characters, or a stopword hit-rate below 8 % on a substantial page sends the
page to vision/OCR instead of letting confident gibberish through.

---

## Scale

| Measure | 120 pages | 500 pages |
|---|---|---|
| Wall time | ~3 s | 11.7 s |
| Peak RSS | < 100 MB | 95 MB |
| Chapter files | 5 | 20 |
| Logo occurrences → stored | 12 → 1 | 50 → 1 |
| EPUBCheck | clean | clean |

What makes that hold:

- **Lazy Tier 2 payloads.** Triage stores scores, not data. Digests and 150 DPI
  rasters are built one batch at a time and released immediately. Building them
  during triage means a 500-page scan materialises hundreds of megabytes of PNG
  before a single page is converted.
- **Image spooling with content-hash filenames.** Raster data goes to a temp
  directory, not the heap, and identical bytes collapse to one file. A logo on
  every page is written once and packaged once.
- **Sampled font profiling.** The baseline is a statistical mode and converges
  long before the whole book is read; `--font-sample-pages` spreads the sample
  across front matter, body and back matter.
- **One extraction per page during triage.** Sanity text is reconstructed from
  the same `get_text("dict")` call used for scoring.

Known ceiling: `ebooklib` holds the complete book in memory during
`write_epub`. For a heavily illustrated 1000-page volume that becomes the
binding constraint, and packaging would need to be replaced with direct
`zipfile` streaming.

---

## Accessibility

Metadata is derived from the emitted document tree, never asserted by default:

- `structuralNavigation` — only when a heading tree exists
- `alternativeText` — only when images exist **and** every one has non-empty alt
- `tableOfContents` — only when tables were emitted
- `dcterms:conformsTo` — `EPUB Accessibility 1.1 - WCAG 2.0 Level AA`

Asserting conformance a file does not meet is worse than asserting nothing, so
the profile is computed after the stream is final.

---

## Tests

```bash
pytest                                    # 136 tests
REQUIRE_EPUBCHECK=1 pytest                # fail if EPUBCheck is missing
RUN_SLOW_TESTS=1 pytest -k five_hundred   # opt-in 500-page run
```

`tests/make_fixtures.py` generates every PDF used by the suite — justified body
text, hyphenated line breaks, inline emphasis, code listings, figures with
captions, a two-column page, a scanned page, a headingless document, and a
configurable long book. No binary fixtures are checked in.

EPUBCheck tests skip when the binary is absent so the suite stays portable, and
hard-fail under `REQUIRE_EPUBCHECK=1` for CI and grading.

---

## Defects found and fixed during the build

Each of these broke a real run, not a review reading.

| Area | Failure | Resolution |
|---|---|---|
| Packaging | Passing an XML-declared document to `EpubHtml.set_content` makes ebooklib's internal parse raise; it swallows the error and emits an **empty chapter** | pass body-level markup only |
| Packaging | `add_item(css)` inserts the stylesheet's raw name, so chapters in a subdirectory get a dangling `<link>` (EPUBCheck `RSC-007`) | compute a relative href |
| Packaging | On short documents a single line near the foot of a page is 100 % frequent and was deleted as a running footer | require ≥4 pages, ≥3 occurrences, and real page geometry |
| Router | Running footers created one backward jump per page; **every** page of a clean book routed to the paid tier | exclude the furniture band from the order metric |
| Router | One order violation scored exactly 85 and slipped back into Tier 1 | 20 points per violation |
| Tier 1 | Comparing each line to the paragraph *origin* made the gap grow per row, truncating every paragraph after line two | track the trailing bbox |
| Tier 1 | Above ~2.5× word spacing the extractor emits each word as its own line, exploding paragraphs into fragments | merge same-baseline fragments, gutter-aware |
| Tier 1 | Words concatenated when the producer positioned them without space glyphs | recover spaces from glyph gaps via `rawdict` |
| Tier 1 | One overhanging line poisoned wrap detection for its whole block | 75th-percentile margin plus a next-word-fit test |
| Tier 1 | Code listings split by their own indentation; indentation then collapsed by HTML | merge contiguous runs, `<pre>`, indent from geometry |
| Tier 2 | Vision cache keyed on `VISION_PAGE_{n}` collided across documents | hash the raster bytes |
| Tier 2 | A short batch response raised, aborting the run after full API spend | re-prompt per page, then deterministic fallback |
| Driver | lxml comment nodes carry a callable `.tag`; `str(tag)` never matches `"comment"` | `isinstance(child.tag, str)` guard |
| Validation | `len(messages)` counted INFO and USAGE as errors, failing valid books | filter `ERROR`/`FATAL` |
| Validation | Ace impact read from `severity`; every violation landed on `minor` | read `earl:impact`, check `earl:outcome` |

---

## Limitations

- Table reconstruction depends on Tier 2. The deterministic engine does not
  infer table structure from vector rules.
- Footnotes are not linked to their references.
- The offline fallback for image-only pages emits an honest placeholder rather
  than silent emptiness; real OCR needs an API key or a local VLM.
- Routing thresholds are hand-calibrated. A labelled page set and a confusion
  matrix would put them on firmer ground.
