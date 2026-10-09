# Hybrid PDF → EPUB3 Converter

A two-tier PDF to EPUB3 pipeline, installable as the `pdf2epub` command.
Clean pages are converted by a deterministic layout engine at zero API cost;
only the pages that genuinely defeat heuristics are sent to a model. Output is
a reflowable, chapter-segmented EPUB3 with accessibility metadata that
reflects what the file actually contains.

Verified on a 500-page book: **11.7 s wall, 95 MB peak RSS, EPUBCheck 5.1.0
clean (0 fatals / 0 errors / 0 warnings)**.

> A complete end-to-end manual — installation, every command and flag, the
> interactive session, credentials, configuration, validation,
> troubleshooting — lives in [USER_GUIDE.md](USER_GUIDE.md).

---

## Install

```bash
# End users (pipx keeps the CLI isolated; plain pip works too)
pipx install .
# or
pip install .

# Development: always inside a project virtual environment — the
# system interpreter intentionally carries none of the optional SDKs
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,nvidia,keyring]"
pytest
```

Optional extras:

| Extra | Purpose |
|---|---|
| `.[openai]` / `.[anthropic]` | Tier 2 model providers |
| `.[keyring]` | OS-keyring credential persistence |

External validators are optional too: **EPUBCheck** (Java) and **Ace by
DAISY** (Node) are discovered on `PATH`; when absent they are skipped and the
CLI says so rather than pretending to have validated. `pdf2epub doctor`
reports what is and is not available.

---

## Use

```bash
# Offline: deterministic tier only, no API key needed
pdf2epub convert book.pdf -o book.epub --provider none

# With a model for the hard pages
export OPENAI_API_KEY=...
pdf2epub convert book.pdf -o book.epub --title "My Book" --author "A. Name"

export ANTHROPIC_API_KEY=...
pdf2epub convert book.pdf -o book.epub --provider anthropic --model claude-sonnet-4-5

# Inspect routing before spending anything
pdf2epub convert book.pdf --report-only

# Interactive session (a terminal launches it bare; pipes use the subcommand)
pdf2epub
pdf2epub interactive

# Diagnostics
pdf2epub doctor [--verify-credentials]
pdf2epub validators
pdf2epub --version
```

### `convert` flags

| Flag | Default | Purpose |
|---|---|---|
| `-o, --output` | `output.epub` | output path (directories created) |
| `--title`, `--author` | from PDF metadata | override publication metadata |
| `--provider` | `none` | provider id (choices from the registry) |
| `--model` | provider's first catalog model | model id for Tier 2 |
| `--batch-size` | `4` | pages per Tier 2 request |
| `--cache-dir` | platform cache dir | LLM response cache (composite-keyed) |
| `--max-repair-attempts` | `2` | validation → repair iterations |
| `--skip-validation` | off | skip the validation gate |
| `--report-only` | off | print the routing table and exit |
| `--font-sample-pages` | `160` | pages sampled for the typography baseline |
| `--no-spool-images` | off | keep extracted images in RAM |
| `--quiet` | off | suppress the progress transcript |
| `--force` | off | overwrite an existing output file |
| `--max-tier2-pages N` | off | refuse to convert when more than N pages need the model |

Exit codes: `0` success, `1` conversion/validation/provider failure,
`2` bad input or usage, `130` interrupted.

### Interactive session

```
$ pdf2epub
pdf2epub> /select      choose the input PDF (title/author default to metadata)
pdf2epub> /export      choose the output path
pdf2epub> /provider    choose and authenticate a provider (hidden key input)
pdf2epub> /model       choose a capability-filtered model
pdf2epub> /status      inspect readiness
pdf2epub> /convert     run the conversion with live progress
```

Also available: `/validators`, `/doctor`, `/config`, `/help`, `/exit`.
Ctrl-C at the prompt clears the line; Ctrl-C during a conversion requests a
clean stop at the next checkpoint (cooperative cancellation).

### Configuration

`pdf2epub` stores small preferences (provider, model, validator toggles,
onboarding choice) in a `config.toml` under the platform config directory
(`platformdirs`: XDG on Linux, `%APPDATA%` on Windows, Application Support on
macOS). Credentials are never written there — they come from environment
variables (`OPENAI_API_KEY`, …), an optional OS keyring, or a session-only
prompt. `pdf2epub doctor` shows the resolved paths and credential sources.

> **Legacy note.** The old `python main.py …` interface was retired. The new
> CLI is deliberately stricter: a named provider with no credential is a
> configuration error instead of a silent offline fallback, the default
> provider is `none`, the cache lives in the platform cache directory, and an
> existing output file is not overwritten without `--force`.

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

### Layers

```
CLI / REPL  →  Application  →  {Providers, Config, Validators}  →  Engine
```

| Layer | Contents |
|---|---|
| `pdf2epub.cli` | `headless` (`convert`/`doctor`/`validators`), `interactive` (REPL, ConsoleIO) |
| `pdf2epub.application` | `ConversionService` (the one typed door to the engine), request/preflight, session, commands, doctor |
| `pdf2epub.providers` | OpenAI/Anthropic-style adapters, profiles, static catalog, registry, route capabilities |
| `pdf2epub.config` | credential resolver (env → keyring), versioned atomic config, platform paths |
| `pdf2epub.validators` | EPUBCheck/Ace wrappers, five-state status, onboarding |
| `pdf2epub.engine` | `driver` (pipeline), `confidence_router`, `tier1_classifier`, `tier2_llm_handler`, `packaging_and_validation`, `events`, `cancellation` |

Layer isolation is enforced by tests: providers/config/validators never import
the engine, the engine imports no provider SDK, and the CLI never touches
`StreamElement`.

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
| Columnar co-occurrence (same-row, stable columns) | ≥ 3 pairs | −20 |
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
  rasters are built one batch at a time and released immediately.
- **Image spooling with content-hash filenames.** Raster data goes to a temp
  directory, not the heap, and identical bytes collapse to one file. A logo on
  every page is written once and packaged once.
- **Sampled font profiling.** The baseline converges long before the whole
  book is read; `--font-sample-pages` spreads the sample across front matter,
  body and back matter.
- **One routing pass.** The service preflights once and hands the payload-free
  reports to the engine (`precomputed_reports`), so triage never runs twice.

Known ceiling: `ebooklib` holds the complete book in memory during
`write_epub`. For a heavily illustrated 1000-page volume that becomes the
binding constraint, and packaging would need to be replaced with direct
`zipfile` streaming.

---

## Accessibility

Metadata is derived from the emitted document tree, never asserted by default:

- `structuralNavigation` — only when a heading tree exists
- `alternativeText` — only when images exist **and** every one has non-empty alt
- `tableOfContents` — only when the navigation document covers top-level headings
- `dcterms:conformsTo` — `EPUB Accessibility 1.1 - WCAG 2.0 Level AA`

Asserting conformance a file does not meet is worse than asserting nothing, so
the profile is computed after the stream is final.

---

## Tests

```bash
pytest                                        # 508 passed, 15 skipped
RUN_DISTRIBUTION_TESTS=1 pytest tests/packaging  # clean-install: build a
                                              # wheel, install into a fresh
                                              # venv outside the repo, drive
                                              # the installed CLI
REQUIRE_EPUBCHECK=1 pytest -k epubcheck       # hard-fail when EPUBCheck is absent
RUN_SLOW_TESTS=1 pytest -k five_hundred       # opt-in 500-page scale run
```

`tests/make_fixtures.py` generates every PDF used by the suite — justified body
text, hyphenated line breaks, inline emphasis, code listings, figures with
captions, two-column and interleaved-two-column pages, a scanned page, a
headingless document, and a configurable long book. No binary fixtures are
checked in. The three test levels: unit (mocked, no network or binaries),
application integration (real service/session/CLI wiring, mocked SDKs and
external tools), and end-to-end (real fixtures through the real engine; real
provider calls are never part of the suite).

CI (`.github/workflows/ci.yml`) runs the unit/integration matrix on Linux,
Windows and macOS across Python 3.10–3.13, a clean-install job, and a pinned
EPUBCheck conformance job.

---

## Defects found and fixed during the build

Each of these broke a real run, not a review reading.

| Area | Failure | Resolution |
|---|---|---|
| Packaging | Passing an XML-declared document to `EpubHtml.set_content` makes ebooklib's internal parse raise; it swallows the error and emits an **empty chapter** | pass body-level markup only; plus a pre-insertion well-formedness gate that fails loudly |
| Packaging | `add_item(css)` inserts the stylesheet's raw name, so chapters in a subdirectory get a dangling `<link>` (EPUBCheck `RSC-007`) | compute a relative href |
| Packaging | On short documents a single line near the foot of a page is 100 % frequent and was deleted as a running footer | require ≥4 pages, ≥3 occurrences, and real page geometry |
| Router | Running footers created one backward jump per page; **every** page of a clean book routed to the paid tier | exclude the furniture band from the order metric |
| Router | One order violation scored exactly 85 and slipped back into Tier 1 | 20 points per violation |
| Router | Row-interleaved two-column emission produced no backward jumps and scrambled in Tier 1 | columnar co-occurrence signal + interleaved fixture |
| Tier 1 | Comparing each line to the paragraph *origin* made the gap grow per row, truncating every paragraph after line two | track the trailing bbox |
| Tier 1 | Above ~2.5× word spacing the extractor emits each word as its own line, exploding paragraphs into fragments | merge same-baseline fragments, gutter-aware |
| Tier 1 | Words concatenated when the producer positioned them without space glyphs | recover spaces from glyph gaps via `rawdict` |
| Tier 1 | One overhanging line poisoned wrap detection for its whole block | 75th-percentile margin plus a next-word-fit test |
| Tier 1 | Code listings split by their own indentation; indentation then collapsed by HTML | merge contiguous runs, `<pre>`, indent from geometry |
| Tier 2 | Vision cache keyed on the page number collided across documents | hash the raster bytes |
| Tier 2 | Offline and failed-model fallbacks were written to the cache, poisoning later online runs | cache only real model responses (schema `v3` invalidates old entries) |
| Tier 2 | A short batch response raised, aborting the run after full API spend | re-prompt per page, then deterministic fallback |
| Repair | Released payloads were reused by self-repair: empty digests, flipped vision flags, pages deleted on empty output | rebuild payloads at repair time; retention guard; scoped re-prompting |
| Validators | Bare `ace` could not launch an npm `.cmd` shim on Windows; reports littered the output folder; timeouts left child processes | one `shutil.which` resolver for detection and execution; temp report dirs; process-tree kill |
| Driver | lxml comment nodes carry a callable `.tag`; `str(tag)` never matches `"comment"` | `isinstance(child.tag, str)` guard |
| Validation | `len(messages)` counted INFO and USAGE as errors, failing valid books | filter `ERROR`/`FATAL` |
| Validation | Ace impact read from `severity`; every violation landed on `minor` | read `earl:impact`, check `earl:outcome` |

---

## Limitations

- **Reflowable only.** Picture books and comics that need fixed-layout EPUB are
  out of scope; image-only pages are embedded as full-page figures.
- Table reconstruction depends on Tier 2; the deterministic engine does not
  infer table structure from vector rules (`pymupdf.find_tables()`-based
  extraction is a planned Tier-1 enhancement).
- Footnotes are not linked to their references.
- A failed vision call falls back to a placeholder paragraph; embedding the
  raster on model failure is a planned improvement.
- Ctrl-C cancellation is cooperative (checked between pages, batches and
  repair attempts). Hard-abort waits until EPUB writing is atomic.
- Routing thresholds are hand-calibrated. A labelled page set and a confusion
  matrix would put them on firmer ground.
- Model selection uses a static catalog; live provider model discovery is
  planned.
