# pdf2epub — The Complete Guide

A complete, A-to-Z manual for the `pdf2epub` command-line tool: a hybrid
PDF to EPUB3 converter. Clean pages are converted by a deterministic
layout engine at zero API cost; only the pages that genuinely defeat the
heuristics are sent to an AI model. The output is a reflowable,
chapter-segmented EPUB3 with accessibility metadata that reflects what the
file actually contains.

This guide covers installation, every command and flag, the interactive
mode, providers and credentials, configuration, validation, diagnostics,
troubleshooting, and a contributor appendix.

---

## Table of contents

1. [About](#1-about)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Quick start](#4-quick-start)
5. [Core concepts](#5-core-concepts)
6. [Convert command reference](#6-convert-command-reference)
7. [Interactive mode (REPL)](#7-interactive-mode-repl)
8. [Providers and credentials](#8-providers-and-credentials)
9. [Configuration file](#9-configuration-file)
10. [Validators](#10-validators)
11. [Doctor](#11-doctor)
12. [Output explained](#12-output-explained)
13. [Troubleshooting](#13-troubleshooting)
14. [Performance and cancellation](#14-performance-and-cancellation)
15. [Limitations](#15-limitations)
16. [FAQ](#16-faq)
17. [Glossary](#17-glossary)
18. [Contributor appendix](#18-contributor-appendix)
19. [Quick reference](#19-quick-reference)

---

## 1. About

`pdf2epub` converts PDF documents into EPUB3 ebooks. It is built around a
single idea: most pages of a normal book are structurally simple, and a
deterministic engine can convert them perfectly and for free. A small
fraction of pages — dense multi-column layouts, scanned pages, pages with
odd typography — genuinely need more, and only those are sent to an AI
model (Tier 2). Everything else is handled offline by a heuristic layout
engine (Tier 1) that costs nothing and works without any API key.

The result is an EPUB that:

- **Reflows** like a native ebook — text adapts to any screen size, unlike
  a fixed PDF page image.
- **Is segmented into chapters** at real heading boundaries, not page
  numbers.
- **Welds paragraphs across page seams** — a paragraph split over pages
  42–43 is reassembled into one.
- **Strips running headers and footers** detected across the whole book.
- **Deduplicates repeated images** — a logo on all 500 pages is stored once.
- **Carries honest accessibility metadata** — conformance is claimed only
  when the emitted document tree actually supports it, never asserted by
  default.

Verified on a 500-page book: **11.7 seconds wall time, 95 MB peak memory,
and a clean EPUBCheck report (0 fatals / 0 errors / 0 warnings).**

> **Migrating from the old interface?** The legacy `python main.py …`
> interface was retired. The new CLI is deliberately stricter: a named
> provider with no credential is a configuration error instead of a silent
> offline fallback, the default provider is `none`, the response cache
> lives in the platform cache directory, and an existing output file is
> never overwritten without `--force`.

---

## 2. Requirements

| Component | Needed for | Notes |
|---|---|---|
| Python 3.10–3.13 | everything | enforced by the package metadata |
| pipx or pip | installation | pipx keeps the CLI isolated |
| Java runtime | EPUBCheck validation (optional) | discovered on `PATH` |
| Node.js | Ace by DAISY accessibility audit (optional) | discovered on `PATH` |
| An AI API key | Tier 2 conversion (optional) | only if you use a model provider |

Operating systems: Linux, Windows and macOS are all supported and tested
in CI.

Nothing else is required. The external validators (EPUBCheck, Ace) are
strictly optional — when they are absent, the CLI says so rather than
pretending to have validated. `pdf2epub doctor` reports what is and is not
available on your machine (see [Doctor](#11-doctor)).

---

## 3. Installation

### End users

```bash
# pipx keeps the CLI and its dependencies isolated (recommended)
pipx install .

# plain pip works too
pip install .
```

Both commands install the `pdf2epub` console command from the project
directory. After installing, verify:

```bash
pdf2epub --version
# pdf2epub 0.1.0
```

### Optional extras

| Extra | Installs | Purpose |
|---|---|---|
| `.[openai]` | `openai` SDK | the `openai` provider (Tier 2) |
| `.[nvidia]` | `openai` SDK | the `nvidia` provider (Tier 2); same client SDK as `.[openai]` |
| `.[anthropic]` | `anthropic` SDK | the `anthropic` provider (Tier 2) |
| `.[keyring]` | `keyring` | OS-keyring credential persistence |
| `.[dev]` | `pytest`, `build` | development and testing |

```bash
# example: install with Anthropic support and keyring persistence
pip install ".[anthropic,keyring]"
```

If you skip an extra and later select that provider, `pdf2epub doctor`
will report the SDK as `OPTIONAL / not installed` — the tool never
mysteriously fails; it tells you what to install.

### External validators (optional)

- **EPUBCheck** (requires Java): download from
  <https://github.com/w3c/epubcheck/releases> and put an `epubcheck`
  wrapper on your `PATH`.
- **Ace by DAISY** (requires Node.js): `npm install -g @daisy/ace`

### Development

```bash
git clone <repository>
cd pdf2epub-converter
pip install -e ".[dev]"
pytest
```

See the [Contributor appendix](#18-contributor-appendix) for the full
test-suite documentation.

---

## 4. Quick start

### Recipe 1 — fully offline, no API key

```bash
pdf2epub convert book.pdf -o book.epub --provider none
```

Every page is handled by the deterministic engine at zero cost. Pages
that would have needed vision/OCR (scanned pages, image-only pages) are
embedded as full-page figures — the tool prints how many, e.g.
`3 visual page(s) embedded directly (no OCR)`.

### Recipe 2 — with a model for the hard pages

```bash
export OPENAI_API_KEY=sk-...          # Linux / macOS
$env:OPENAI_API_KEY = "sk-..."        # Windows PowerShell

pdf2epub convert book.pdf -o book.epub --title "My Book" --author "A. Name"
```

Simple pages still cost nothing; only routed-out pages are sent to the
model.

### Recipe 3 — inspect before spending

```bash
pdf2epub convert book.pdf --report-only
```

Prints the per-page routing table and a cost advisory, then exits
without converting and without spending anything:

```
  page | score | target        | sigma | order | columns | vectors | reason
  -----+-------+---------------+-------+-------+---------+---------+-------------------
     1 |    96 | tier1         |  0.42 |     0 |       0 |       2 | clean
    17 |    58 | tier2-digest  |  6.10 |     2 |       0 |       0 | font_variance:-31,reading_order:-40
   204 |     0 | tier2-vision  |  0.00 |     0 |       0 |       3 | sanity:no_text_layer
...
~12 Tier-2 page(s) (9 digest, 3 vision)
```

(Example values.) Every page that will cost money is listed before a
single request is made.

### Recipe 4 — interactive session

```bash
pdf2epub              # launches the interactive prompt when a terminal is attached
```

See [Interactive mode (REPL)](#7-interactive-mode-repl).

---

## 5. Core concepts

### The two tiers

Every page is scored 0–100 and routed at a threshold of 85:

| Tier | Handles | Cost |
|---|---|---|
| Tier 1 — deterministic engine (PyMuPDF heuristics) | score ≥ 85: plain text, headings, lists, code, figures with captions | $0, no key needed |
| Tier 2 — model (digest) | score < 85 with a usable text layer: multi-column layouts, odd reading order, dense typography | ~$0.002 per page |
| Tier 2 — model (vision/OCR) | pages that fail the sanity gate: no text layer, corrupted encodings, scanned pages | ~$0.002 per page |

With `--provider none` there is no Tier 2 at all: vision-class pages are
embedded as full-page figures, and digest-class pages fall back to the
deterministic engine.

### The routing score

Four signals feed the score. Penalties subtract from 100:

| Signal | Threshold | Penalty |
|---|---|---|
| Weighted font-size deviation (σ) | > 3.5 pt | `min(35, (σ − 3.5) × 12)` |
| Reading-order violations | > 0 | `min(45, n × 20)` |
| Columnar co-occurrence (same-row blocks in stable columns) | ≥ 3 pairs | −20 |
| Vector path density | > 20 | `min(30, (n − 20) × 1.5)` |

The threshold is deliberately strict because the two error directions do
not cost the same: a simple page wrongly sent to Tier 2 wastes ~$0.002,
but a complex page wrongly kept in Tier 1 is silently corrupted. Reading
order is measured over body content only, so running headers/footers do
not push an entire clean book onto the paid tier.

### The sanity gate

Before scoring, each page's text is sanity-checked. A page is sent
straight to vision/OCR when:

- it has **no text layer** at all (scanned page), or
- more than **15 %** of its characters are private-use, replacement or
  control characters (corrupted font encoding), or
- its **stopword hit-rate is below 8 %** on a substantial page — confident
  gibberish must not pass.

These appear in the routing table as reasons like
`sanity:no_text_layer`, `sanity:pua_saturation` or
`sanity:lexical_gibberish`.

### The unified stream

Page boundaries are not file boundaries. After extraction, all pages
merge into one document stream for the whole book:

- a paragraph straddling pages 42–43 is welded back together,
- running headers/footers are detected book-wide (≥ 4 pages, ≥ 3
  occurrences, real page geometry required) and removed,
- chapter files are cut at **heading nodes**, not page numbers,
- identical images (e.g. a logo repeated on every page) collapse to one
  stored file via content hashing.

### Validation and self-repair

After packaging, the EPUB passes a validation gate: internal structural
checks plus the enabled external validators (EPUBCheck, Ace). On failure,
the pipeline repairs and re-validates, up to `--max-repair-attempts`
(default 2) passes. `--skip-validation` bypasses the gate entirely.

### Metadata fallback

Title and author resolve in this order: your `--title`/`--author` flag →
the PDF's own metadata → the document's first-page opening heading
(only when it is the first content on page one and not a running
header) → engine defaults (`Untitled Publication` / `Unknown Author`).

---

## 6. Convert command reference

```
pdf2epub convert <pdf_path> [options]
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `-o, --output PATH` | `output.epub` | output EPUB path; parent directories are created |
| `--title TEXT` | PDF metadata | override the publication title |
| `--author TEXT` | PDF metadata | override the author |
| `--provider ID` | saved config, else `none` | AI provider for complex pages; choices come from the registry (`none`, `openai`, `anthropic`, `nvidia`) |
| `--model ID` | saved config, else the provider's first catalog model | Tier 2 model id |
| `--batch-size N` | `4` | pages per Tier 2 request (≥ 1) |
| `--cache-dir PATH` | platform cache dir | LLM response cache location |
| `--max-repair-attempts N` | `2` | validation → repair iterations (≥ 0) |
| `--skip-validation` | off | skip the validation gate |
| `--report-only` | off | print the routing table and exit without converting |
| `--font-sample-pages N` | `160` | pages sampled for the typography baseline (≥ 1) |
| `--no-spool-images` | off | keep extracted images in RAM instead of a temp directory |
| `--quiet` | off | suppress the progress transcript (warnings/errors still print, to stderr) |
| `--force` | off | overwrite an existing output file |
| `--max-tier2-pages N` | off (uncapped) | refuse to convert when more than N pages need the model |

### How options resolve (precedence)

CLI flag → saved `config.toml` → built-in default. For example: an
omitted `--provider` falls back to the provider saved by the REPL
(`/provider` → "Save as default provider?"), and then to `none`. An
omitted `--cache-dir` falls back to `[paths] cache_dir` in the config
file, then to the platform cache directory. See
[Configuration file](#9-configuration-file).

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | conversion, validation or provider failure (config-class errors) |
| `2` | bad input or usage (missing PDF, bad output path, argparse errors) |
| `130` | interrupted (Ctrl-C) |

Warnings print as `[WARNING] …` and errors as `[ERROR] …` on stderr;
the routing table and transcript print on stdout.

### The progress transcript

Without `--quiet`, a conversion prints its phases:

```
[PHASE 1-2] Opening book.pdf
            'The Example Book' by A. Author - 500 page(s)
            baseline: Helvetica 10.0pt, line height 12.0pt (sampled 160/500 pages)

[PHASE 3] Triage & routing
            triage: 100/500 (20%)
            ...
            tier1=488  tier2-digest=9  tier2-vision=3

[PHASE 4A] Tier 1 deterministic engine (488 pages)
            tier1: 98/488 (20%)
            ...

[PHASE 4B] Tier 2 AI engine (12 pages)
            model batch: 4 page(s)
            tier2: 4/12 (33%)
            ...

[PHASE 5] Merging unified document stream

[PHASE 6] Packaging EPUB3

[PHASE 7] Validation gate
```

Progress ticks at 5 % boundaries. A fully scanned document reports
`no text layer found - every page will go to vision/OCR` during profiling.
Offline conversions with vision-class pages print
`N visual page(s) embedded directly (no OCR)`.

### `--report-only` details

A dry run:

- routes the whole document but builds no payloads and spends nothing,
- prints the per-page routing table and the cost advisory,
- skips provider/credential/model checks entirely (a dry run cannot
  spend, so capability mismatches are shown as warnings, not errors),
- skips output-path checks — nothing is written.

`--report-only` is the recommended first step on any new or expensive
document.

### `--max-tier2-pages` details

The spend cap is checked after routing but **before any provider
request**. When the routed Tier 2 page count exceeds the cap, the run
refuses with a configuration error rather than spending:

```
[ERROR] tier-2 pages (214) exceed --max-tier2-pages (50);
        raise the cap or inspect with --report-only
```

`--report-only` runs are exempt by design.

### `--batch-size` guidance

Pages are grouped into one Tier 2 request per batch. Larger batches mean
fewer requests; smaller batches mean finer-grained cancellation
checkpoints and less re-prompting when a short response must be retried
per page. Must be ≥ 1.

### `--force` and output safety

An existing output file is never clobbered silently:

```
[ERROR] output already exists (pass --force to overwrite): book.epub
```

Output directories are created automatically, and the EPUB write itself
is atomic — a crash or interrupt never leaves a half-written `.epub`.

---

## 7. Interactive mode (REPL)

Launch:

```bash
pdf2epub                  # bare command: interactive when a terminal is attached
pdf2epub interactive      # explicit: works even when input is piped/scripted
```

The bare command requires a TTY. Without one it prints usage and exits
with code `2`, suggesting `pdf2epub convert …` or `pdf2epub interactive`
instead. Piped/scripted sessions never run onboarding (no config side
effects); the explicit `interactive` subcommand is never refused.

On startup you see:

```
pdf2epub interactive session - /help for commands, /exit to quit
```

If external validators are enabled but not installed, a one-time
onboarding notice offers: `1. Show install instructions`,
`2. Skip for this session`, `3. Don't show again` (choice 3 persists in
the config file).

### Commands

Available everywhere: `/config`, `/convert`, `/doctor`, `/export`,
`/exit`, `/help`, `/model`, `/provider`, `/select`, `/status`,
`/validators`. Commands are case-insensitive and a command bug can never
kill the session — it is reported and the loop continues.

#### `/select` — choose the input PDF

```
pdf2epub> /select
PDF path: book.pdf
Title [leave empty for The Example Book]:
Author [leave empty for A. Author]:
selected: book.pdf
title:   The Example Book
author:  A. Author
output:  book.epub
```

- The path must exist and be a file.
- Title/author default to the PDF's own metadata; leave empty to accept.
- The output path is derived automatically as `<pdf-stem>.epub` inside
  the configured output directory (see
  [Configuration file](#9-configuration-file)) — or use `/export`.

#### `/export` — choose the output EPUB path

Prompts for `Output path: `, creates parent directories, and when the
file already exists asks `book.epub exists - overwrite? (y/N):`. If you
decline, the existing file is protected: `/convert` will refuse until
you allow overwrite here or pick another path.

#### `/provider` — choose and authenticate a provider

```
pdf2epub> /provider
Available providers:
  1. none (none)
  2. OpenAI (openai)
  3. Anthropic (anthropic)
  4. NVIDIA (nvidia)
Select: 2
Using credential from environment (OPENAI_API_KEY).
Verify credentials now? (y/N): n
Save as default provider? (y/N): y
Saved to config.
provider: openai (choose a model with /model)
```

- Select by number or by id. `none` = explicit offline mode.
- If no credential is found, you are prompted for the key with hidden
  input (`API key: `) — it stays in the session, never on disk, never in
  output.
- You can verify the credential against the provider live
  (`Credentials verified.` / `Credentials rejected.`), store a manual key
  in the OS keyring for later sessions, and save the provider as the
  persistent default.
- **Changing providers invalidates** the model, the credential and the
  routing plan — a key for one provider is never offered to another.

#### `/model` — choose the conversion model

Lists the provider's non-retired catalog models (numbered), marks any
that are `(incompatible with current routing)` based on the last routing
plan, and accepts either a number or a custom model id (custom ids are
allowed — preflight ultimately decides and warns):

```
pdf2epub> /model
Models:
  1. GPT-4o [gpt-4o]
  2. GPT-4o mini [gpt-4o-mini]
Select (number or model id): 2
model: gpt-4o-mini
```

#### `/status` — inspect readiness

```
PDF        : book.pdf
Title      : (from PDF metadata)
Author     : (from PDF metadata)
Output     : book.epub
Provider   : openai
Model      : gpt-4o-mini
Credential : environment
Routing    : tier1=488 digest=9 vision=3
EPUBCheck  : enabled
Ace        : enabled
Ready      : READY
```

Credential shows `manual (this session)`, the resolved source
(`environment`, `keyring`, …) or `not available`. The `Routing` line
appears after a conversion. Readiness states:

- `READY` — nothing missing.
- `READY_WITH_PREFLIGHT_REQUIRED` — configured for an online provider but
  no routing has run yet (the first `/convert` runs it).
- `NOT_READY` — with the exact gaps, e.g. `PDF not selected (/select)`,
  `output path not set (/export)`, `provider not chosen (/provider)`,
  `no credential for 'openai' (set OPENAI_API_KEY or use /provider)`,
  `model not selected (/model)`. `/convert` refuses while any gap exists.

#### `/convert` — run the conversion

Re-checks readiness, then converts with live progress rendered from
pipeline events (phase starts, `model batch: 4 page(s)`,
`validating...`, `repair pass 1`, page counters at 10 % boundaries).
On success: `done: book.epub`. The routing plan from the run is kept for
`/status` and `/model` compatibility checks.

#### `/doctor`, `/validators`, `/config`

REPL front doors to the headless equivalents (see
[Doctor](#11-doctor) and [Validators](#10-validators)). `/config` shows
the saved configuration including the resolved cache dir and the config
file path.

#### `/exit` — leave the session

Also EOF (Ctrl-D on Linux/macOS, Ctrl-Z + Enter on Windows) exits
cleanly with code 0.

### Ctrl-C semantics

- **At the prompt** (or while a command is asking a question): clears the
  line; the session continues.
- **During a conversion**: requests a clean stop at the next checkpoint
  (cooperative cancellation, checked between pages, batches and repair
  passes) and prints `cancelling - stopping at the next checkpoint`.
  Pressing Ctrl-C again is idempotent. A hard abort waits for the atomic
  EPUB write rather than corrupting the output.

---

## 8. Providers and credentials

### Built-in providers

| id | Name | Credential environment variable | Catalog models |
|---|---|---|---|
| `none` | offline mode | — (no credential needed) | — |
| `openai` | OpenAI | `OPENAI_API_KEY` | `gpt-4o`, `gpt-4o-mini` |
| `anthropic` | Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5` |
| `nvidia` | NVIDIA | `NVIDIA_API_KEY` | `moonshotai/kimi-k3`, `deepseek-ai/deepseek-v4.1-flash` |

All catalog models accept image input and structured output. Model ids
not in the catalog are accepted as custom ids with an advisory warning
(`model 'x' is not in provider 'openai''s static catalog; proceeding
without capability verification`) — the live endpoint remains the final
judge.

### The credential resolution chain

Credentials are resolved in this order, and the resolved source is what
`doctor` and `/status` report:

1. **Manual key** for this session (typed into `/provider`'s hidden
   prompt) — never written anywhere.
2. **Provider environment variable** (`OPENAI_API_KEY`,
   `ANTHROPIC_API_KEY`, `NVIDIA_API_KEY`, …).
3. **Generic variable** `PDF2EPUB_API_KEY` — only for providers that
   explicitly opt in (none of the built-in user-facing providers do; it
   exists for OpenAI-compatible aggregators).
4. **OS keyring** (service `pdf2epub`, one entry per provider id) —
   requires the `.[keyring]` extra.
5. **Unavailable** — and then a *named* provider is a configuration
   error, not a silent offline fallback.

```bash
# Linux / macOS
export OPENAI_API_KEY=sk-...

# Windows PowerShell (current session)
$env:OPENAI_API_KEY = "sk-..."

# Windows CMD (current session)
set OPENAI_API_KEY=sk-...

# Windows (persistent, new terminals)
setx OPENAI_API_KEY "sk-..."
```

### Secret hygiene — what the tool guarantees

- Credentials are **never written to `config.toml`** (the schema has no
  secret-bearing fields; tests enforce this).
- A manual key **never reaches logs, prompts or written output**
  (tests assert the secret string cannot appear in session output).
- Changing providers **clears the manual key** so it can never leak to
  another provider.
- Keyring failures (locked keychain, headless Linux, missing dbus)
  degrade to "unavailable" quietly — resolution never raises.

### Verifying and persisting

- `pdf2epub doctor --verify-credentials` contacts the configured
  provider and reports `verified` or `rejected by the provider`. This is
  the **only** operation in the tool that touches the network
  diagnostically.
- In the REPL, `/provider` offers live verification and keyring storage;
  `/doctor` offers verification when a credential is found.

### Cost control

- `--report-only` — see exactly which pages would cost money before
  spending.
- `--max-tier2-pages N` — hard refusal above the cap, before any request.
- Response cache — identical page payloads are never re-billed across
  runs (see [Output explained](#12-output-explained) for cache
  contents). Only real model responses are cached; offline/fallback
  output is never cached.

---

## 9. Configuration file

`pdf2epub` stores small preferences (default provider, model, validator
toggles, onboarding choice, output/cache locations) in a `config.toml`
under the platform config directory. Credentials are never stored there
(see [Providers and credentials](#8-providers-and-credentials)).

### Locations

| | Windows | Linux | macOS |
|---|---|---|---|
| Config file | `%APPDATA%\pdf2epub\config.toml` | `~/.config/pdf2epub/config.toml` | `~/Library/Application Support/pdf2epub/config.toml` |
| Cache dir | `%LOCALAPPDATA%\pdf2epub\cache` | `~/.cache/pdf2epub` | `~/Library/Caches/pdf2epub` |
| Logs dir | `%LOCALAPPDATA%\pdf2epub\logs` | `~/.local/state/pdf2epub/log` | `~/Library/Logs/pdf2epub` |

Paths are resolved via `platformdirs` (`appauthor=False`, so no redundant
vendor subfolder). `pdf2epub doctor` shows the resolved config path and
`/config` in the REPL shows cache dir + config file path.

### Full schema (all keys, annotated)

```toml
schema_version = 1          # managed by the tool; do not edit

[application]
validators_notice = "always"   # "always" or "never": show the missing-validator
                                # onboarding notice in the interactive session

[provider]
name = "openai"               # default provider id; absent = follow the default (none)
conversion_model = "gpt-4o"   # default model id; absent = provider's first catalog model

[validator]
epubcheck = true              # include EPUBCheck in the validation gate
ace = true                     # include Ace by DAISY in the validation gate

[defaults]
output_directory = "."         # default directory for REPL-derived output paths

[paths]
cache_dir = "D:/epub-cache"    # LLM response cache; absent = platform cache dir
```

Every key is optional: a missing key means "follow the built-in default"
— the file never materializes sections you did not set.

### Behavior guarantees

- **Reads never raise**: a missing, empty, corrupt or future-versioned
  file degrades to in-memory defaults with a warning. A config written by
  a newer pdf2epub still applies its known fields.
- **Writes are atomic**: unique temp file + replace, so a crash mid-save
  can never corrupt the file (Windows-safe).
- **Load performs zero filesystem mutations** — read-only runs stay
  read-only.
- Unknown keys in the file are ignored on load (forward compatible) but
  rejected on save (typo protection).

### How settings are usually changed

You rarely edit the file by hand. Preferences are written for you by:

- `/provider` — the "Save as default provider?" offer persists
  `[provider] name`;
- `/validators` — the toggle menu persists `[validator]` settings;
- the onboarding notice — choice 3 ("Don't show again") persists
  `[application] validators_notice = "never"`.

The default model (`[provider] conversion_model`) has no in-app writer:
set it by hand in the file, or rely on the session (`/model`) and the
CLI (`--model`) instead.

### Config precedence for a conversion

CLI flag → session state (REPL) → `config.toml` → built-in default. The
REPL reloads the config file for **every** conversion, so toggling
validators mid-session affects the very next `/convert`.

---

## 10. Validators

Two external validators are supported, both optional:

| Validator | Requires | Installs via |
|---|---|---|
| EPUBCheck (W3C, EPUB conformance) | Java | download from <https://github.com/w3c/epubcheck/releases>, put an `epubcheck` wrapper on `PATH` |
| Ace by DAISY (accessibility audit) | Node.js | `npm install -g @daisy/ace` |

Validators are discovered on `PATH` once and used for both detection and
execution. When a validator is missing it is **skipped with a clear
notice** — the tool never pretends to have validated.

### Validator states

| State | Meaning |
|---|---|
| `available` | enabled, installed, runs |
| `disabled` | turned off in the config file |
| `required_but_missing` | enabled in the config but not installed |
| `failed_to_run` | installed but the probe/version check failed |

### Validator commands

```bash
pdf2epub validators
```

prints one line per validator, e.g.:

```
  EPUBCheck      available
  Ace by DAISY   required_but_missing
```

In the REPL, `/validators` shows the same list plus a menu:
`1. Show install instructions`, `2. Toggle a validator's enabled state`
(persisted to the config file), `3. Back`.

The validation gate itself runs during every conversion unless
`--skip-validation` is passed: internal structural checks first, then
each enabled external validator. Failures trigger repair passes (see
[Core concepts](#5-core-concepts)).

---

## 11. Doctor

```bash
pdf2epub doctor [--verify-credentials]
```

`doctor` inspects the local environment and prints one line per check:
`name`, a state (`OK` / `WARN` / `FAIL` / `OPTIONAL`) and a detail. It
performs **no network operations** unless `--verify-credentials` is
passed. Exit code `1` when any check is `FAIL`, otherwise `0`.

### What it checks

| Check | States | Detail shows |
|---|---|---|
| `python` | OK / WARN | version (WARN below 3.10) |
| `core packages` | OK / FAIL | pymupdf, ebooklib, lxml present or the missing list |
| `openai` / `anthropic` / `keyring` | OK / OPTIONAL | installed, or what the extra is needed for |
| `java` / `node` | OK / WARN / OPTIONAL | resolved path and probed version |
| `EPUBCheck` / `Ace by DAISY` | OK / OPTIONAL / WARN | version; `disabled in configuration`; or `required_but_missing` (enabled but not installed — fix by installing or toggling off) |
| `config` | OK / WARN | file path, "no file yet (defaults in use)", invalid TOML, or newer-schema warning |
| `output directory` | OK / WARN | writability (created on demand) |
| `credentials` | OK / OPTIONAL / WARN | source (`from environment`, `manual key (this session)`, …) or `missing (set OPENAI_API_KEY)` |
| `credential verification` | OK / FAIL / WARN | `verified` / `rejected by the provider` (only with `--verify-credentials`) |
| `model fit` | OK / WARN | compatibility of the selected model with the last routing plan (REPL session-aware) |

A missing optional tool is never a `FAIL` — optional tooling must not
fail your machine's report. The states mean:

- **OK** — present and working.
- **WARN** — informational problem worth fixing (a validator enabled in the
  config but not installed, invalid config TOML, a rejected credential, a
  probe failure).
- **FAIL** — a hard problem (a core dependency is missing, or
  `--verify-credentials` was rejected by the provider).
- **OPTIONAL** — not installed and not required for the current
  configuration.

### Recommended workflow for a new machine

```bash
pdf2epub doctor                      # what's installed, what's optional
pdf2epub doctor --verify-credentials  # (provider configured) is the key valid?
pdf2epub convert book.pdf --report-only   # what would this book cost?
pdf2epub convert book.pdf -o book.epub --max-tier2-pages 100
```

---

## 12. Output explained

### What's inside the EPUB

- **Reflowable XHTML chapters**, cut at heading boundaries (a 500-page
  book becomes ~20 chapter files; a 120-page book ~5).
- **A navigation document (TOC)** derived from the heading tree.
- **Deduplicated images** with content-hash filenames; identical bytes
  are stored and packaged once.
- **Code listings** in `<pre>` blocks with indentation preserved from
  page geometry.
- **Accessibility metadata**, derived from what the file actually
  contains:
  - `structuralNavigation` — only when a heading tree exists;
  - `alternativeText` — only when images exist **and** every one has
    non-empty alt text;
  - `tableOfContents` — only when the navigation document covers
    top-level headings;
  - `dcterms:conformsTo` — `EPUB Accessibility 1.1 - WCAG 2.0 Level AA`.

  Claiming conformance a file does not meet is worse than claiming
  nothing, so the profile is computed after the document stream is final.
  EPUB readers expose this metadata in their accessibility info panel.

### Where the by-products live

| Path | Contents |
|---|---|
| output file | the `.epub` (written atomically — a crash never leaves a partial file) |
| cache dir | LLM response cache (`composite-keyed`; vision entries keyed on the raster's byte hash so identical scans hit across documents; only real model responses are cached — schema `v3` invalidates old/fallback entries) |
| temp spool dir | extracted raster images during a conversion (`--no-spool-images` keeps them in RAM instead); cleaned up automatically |
| logs dir | diagnostic logging |

Clearing the cache directory is always safe; it only costs re-billing on
the next conversion of the same content.

### Reading it in a reader

Any EPUB3-capable reader works: Calibre, Apple Books, Thorium, Google
Play Books, Kobo (EPUB3), etc. The text reflows to the screen; chapter
navigation follows the heading tree, not the original page numbers.

---

## 13. Troubleshooting

Exit codes first: `0` success, `1` conversion/config/provider failure,
`2` bad input or usage, `130` interrupted.

| Message / symptom | Cause | Fix |
|---|---|---|
| `input not found: …` / `input is not a file: …` | bad PDF path (exit 2) | correct the path |
| `output path is a directory: …` | `-o` points at a directory (exit 2) | give a file path |
| `cannot create output directory …` | unwritable parent (exit 2) | fix permissions or choose another `-o` |
| `output already exists (pass --force to overwrite): …` | safety refusal (exit 2) | add `--force` or a new `-o` |
| `PDF is password protected; decrypt it first.` | encrypted PDF (exit 2) | remove the password with another tool first |
| `PDF contains no pages.` | empty document (exit 2) | check the source file |
| `cannot open PDF: …` | corrupt/unreadable file (exit 2) | re-export or repair the PDF |
| `no credential for provider 'openai': set OPENAI_API_KEY or configure it via \`pdf2epub\`` | named provider without a resolvable key (exit 1) | set the env var, use `/provider`, or `--provider none` |
| `provider 'openai' requires a conversion_model` | online provider, no model (exit 1) | pass `--model` or use `/model` |
| `unknown provider 'x'; known: […]` | typo in `--provider` (exit 1) | use a registry id: `none`, `openai`, `anthropic`, `nvidia` |
| `batch_size must be >= 1` (also `max_repair_attempts`, `font_sample_pages`, `max_tier2_pages` bounds) | invalid numeric flag (exit 1) | fix the value |
| `tier-2 pages (N) exceed --max-tier2-pages (cap)…` | spend cap refused the run (exit 1) | raise the cap or inspect with `--report-only` first |
| `model 'x' cannot handle vision pages (needs image input…)` | selected model lacks a capability the document needs (exit 1) | pick another model; `--report-only` shows which routes are needed |
| `model 'x' is not in provider …'s static catalog; proceeding without capability verification` | custom model id (warning) | fine if the id is valid on the wire; otherwise pick a catalog model |
| `conversion_model is ignored for the offline provider` | `--model` with `--provider none` (warning) | harmless |
| `[WARNING] Validation still failing after repair attempts.` | validation gate failed after repairs (exit 1) | run `pdf2epub doctor`, install validators, try `--max-repair-attempts 3`; report the document if it persists |
| validators reported missing | EPUBCheck/Ace not installed | install them (see [Validators](#10-validators)) or expect the notice; conversion still runs |
| `cancelled` (exit 130) | Ctrl-C | nothing wrong; partial EPUBs are never written |
| keyring store failed / key not found | backend unavailable (headless Linux, locked keychain) | use the environment variable instead |
| config warnings: `ignoring unreadable config … (TOMLDecodeError)` / `written by a newer pdf2epub` | corrupt or newer-versioned `config.toml` | known fields still apply; fix or delete the file to reset defaults |

When in doubt, run `pdf2epub doctor` — it resolves paths, probes
dependencies and explains every gap.

---

## 14. Performance and cancellation

### Verified scale

| Measure | 120 pages | 500 pages |
|---|---|---|
| Wall time | ~3 s | 11.7 s |
| Peak RSS | < 100 MB | 95 MB |
| Chapter files | 5 | 20 |
| Logo occurrences → stored | 12 → 1 | 50 → 1 |
| EPUBCheck | clean | clean |

### Why it holds up

- **Lazy Tier 2 payloads** — routing stores scores, not data; rasters and
  digests are built one batch at a time and released immediately.
- **Image spooling** — raster data goes to a temp directory, not the heap,
  with content-hash filenames (`--no-spool-images` flips this for
  RAM-disk-class machines).
- **Sampled font profiling** — `--font-sample-pages` (default 160)
  spreads the typography baseline across front matter, body and back
  matter instead of reading the whole book. Lower it for very short
  documents; the default converges long before page 160 on most books.
- **One routing pass** — the service preflights once and hands the
  payload-free reports to the engine, so routing never runs twice.

### Known ceiling

`ebooklib` holds the complete book in memory during the EPUB write. For
a heavily illustrated 1000-page volume that becomes the binding
constraint.

### Cancellation

Cancellation is **cooperative**: the stop request is checked between
pages, between model batches, and between repair attempts. In the REPL,
Ctrl-C during a conversion requests the stop (`cancelling - stopping at
the next checkpoint`); at the prompt it just clears the line. The final
EPUB write is atomic, so an interrupted run leaves either the previous
file or the complete new file — never a corrupt half.

---

## 15. Limitations

- **Reflowable only.** Picture books and comics that need fixed-layout
  EPUB are out of scope; image-only pages are embedded as full-page
  figures.
- **Table reconstruction depends on Tier 2.** The deterministic engine
  does not infer table structure from vector rules (a
  `pymupdf.find_tables()`-based Tier 1 enhancement is planned).
- **Footnotes are not linked** to their references.
- **A failed vision call falls back to a placeholder paragraph**;
  embedding the raster on model failure is a planned improvement.
- **Ctrl-C is cooperative** — see [Performance and
  cancellation](#14-performance-and-cancellation).
- **Routing thresholds are hand-calibrated**; a labelled page set and a
  confusion matrix would put them on firmer ground.
- **Model selection uses a static catalog**; live provider model
  discovery is planned (custom ids work meanwhile, with an advisory
  warning).

---

## 16. FAQ

**Do I need an API key?**
No. `--provider none` (the default) converts entirely offline. Pages
that would need OCR are embedded as images instead of transcribed.

**What does a conversion cost?**
Only Tier 2 pages are billed, ~$0.002 each. A typical clean book routes
95–100 % to Tier 1 and costs nothing. Run `--report-only` first and read
the cost advisory.

**My book is a scan. Will it work?**
With a provider configured, scanned pages route to vision/OCR and are
transcribed by the model. Fully offline, they are embedded as full-page
figures (no OCR) — the transcript tells you how many.

**Why does `--provider openai` fail without a key instead of just going offline?**
By design: a named provider with no credential is a configuration
error, not a silent fallback. Otherwise you would believe you got
Tier 2 quality while silently receiving Tier 1 output.

**Where is my config / cache?**
See the paths table in [Configuration file](#9-configuration-file), or
run `pdf2epub doctor` and REPL `/config` to see the resolved paths.

**Is my API key stored anywhere?**
Never in `config.toml`. Environment variables and the OS keyring
(optional `.[keyring]` extra) are the persistent options; a manual key
in the REPL exists only for that session.

**Why were some simple-looking pages sent to the model?**
The router scores four structural signals (font variance, reading
order, columns, vector density) plus a text sanity gate — things that
are invisible to the eye but corrupt deterministic extraction. The
routing table's `reason` column shows exactly which signal fired on
each page.

**Is the EPUB accessible?**
Accessibility metadata is derived from the emitted document tree and
only claimed when true (heading navigation, complete alt text, TOC).
Install Ace by DAISY to audit the result against WCAG.

**Can I overwrite `book.epub` without deleting it?**
Yes: `--force` (headless) or answer `y` at `/export`'s overwrite
prompt (REPL).

---

## 17. Glossary

| Term | Meaning |
|---|---|
| Tier 1 | the deterministic, offline layout engine (PyMuPDF-based) |
| Tier 2 | the model-assisted path for pages that defeat Tier 1 |
| digest route | Tier 2 request built from a JSON bounding-box digest of a text page |
| vision route / OCR | Tier 2 request built from a 150 DPI raster of the page |
| routing score | 0–100 page confidence; threshold 85 |
| sanity gate | pre-scoring check for no-text/corrupted/gibberish pages |
| preflight | the routing + capability check that runs before any spend |
| spooling | writing extracted images to a temp dir instead of RAM |
| welding | rejoining a paragraph split across a page seam |
| furniture | running headers/footers, stripped after book-wide detection |
| EPUBCheck | W3C's EPUB conformance validator (Java, optional) |
| Ace by DAISY | accessibility audit tool (Node.js, optional) |
| keyring | the OS credential store (service `pdf2epub`) |
| reflowable | text adapts to screen size, as opposed to fixed-layout |
| cooperative cancellation | a stop requested at checkpoints, never mid-write |
| composite-keyed cache | response cache keyed on provider+model+payload (rasters hash on bytes) |

---

## 18. Contributor appendix

### Running the tests

```bash
pytest                                          # full unit + integration suite
RUN_DISTRIBUTION_TESTS=1 pytest tests/packaging # clean-install: build a wheel,
                                                # install into a fresh venv outside
                                                # the repo, drive the installed CLI
REQUIRE_EPUBCHECK=1 pytest -k epubcheck         # hard-fail when EPUBCheck is absent
RUN_SLOW_TESTS=1 pytest -k five_hundred         # opt-in 500-page scale run
```

On Windows PowerShell, set the opt-in variables as environment variables
first (`$env:RUN_DISTRIBUTION_TESTS = "1"`).

### Test levels

1. **Unit** — mocked, no network or external binaries.
2. **Application integration** — real service/session/CLI wiring with
   mocked SDKs and external tools.
3. **End-to-end** — real fixtures through the real engine. Real provider
   calls are never part of the suite.

### Fixtures

`tests/make_fixtures.py` generates every PDF used by the suite —
justified body text, hyphenated line breaks, inline emphasis, code
listings, figures with captions, two-column and interleaved two-column
pages, a scanned page, a headingless document, and a configurable long
book. **No binary fixtures are checked in.**

### CI

`.github/workflows/ci.yml` runs the unit/integration matrix on Linux,
Windows and macOS across Python 3.10–3.13, a clean-install job, and a
pinned EPUBCheck conformance job.

### Layer rules (enforced by tests)

- `providers` / `config` / `validators` never import the engine.
- The engine imports no provider SDK.
- The CLI never touches `StreamElement` directly.

### Layout of the source

```
CLI / REPL  →  Application  →  {Providers, Config, Validators}  →  Engine
```

| Layer | Contents |
|---|---|
| `pdf2epub.cli` | `headless` (`convert`/`doctor`/`validators`), `interactive` (REPL, ConsoleIO) |
| `pdf2epub.application` | `ConversionService`, request/preflight, session, commands, doctor |
| `pdf2epub.providers` | OpenAI/Anthropic-style adapters, profiles, static catalog, registry, route capabilities |
| `pdf2epub.config` | credential resolver (env → keyring), versioned atomic config, platform paths |
| `pdf2epub.validators` | EPUBCheck/Ace wrappers, five-state status, onboarding |
| `pdf2epub.engine` | `driver` (pipeline), `confidence_router`, `tier1_classifier`, `tier2_llm_handler`, `packaging_and_validation`, `events`, `cancellation` |

---

## 19. Quick reference

```text
Commands
  pdf2epub convert <pdf> [flags]   convert (the workhorse)
  pdf2epub doctor [--verify-credentials]
  pdf2epub validators
  pdf2epub interactive             REPL (bare `pdf2epub` needs a TTY)
  pdf2epub --version / -V

convert flags
  -o, --output PATH        default output.epub
  --title / --author       default: PDF metadata
  --provider ID            none | openai | anthropic | nvidia   (default none)
  --model ID               default: provider's first catalog model
  --batch-size N           default 4        (>= 1)
  --max-repair-attempts N  default 2        (>= 0)
  --max-tier2-pages N      spend cap, checked before any request
  --font-sample-pages N    default 160      (>= 1)
  --cache-dir PATH         default: platform cache dir
  --report-only            routing table + cost advisory, no conversion
  --skip-validation        bypass the validation gate
  --no-spool-images        keep images in RAM
  --quiet                  no transcript (warnings/errors still print)
  --force                  overwrite existing output

Exit codes
  0 success   1 failure   2 bad input/usage   130 interrupted

REPL
  /select /export /provider /model /status /convert
  /doctor /validators /config /help /exit

Environment
  OPENAI_API_KEY / ANTHROPIC_API_KEY   provider credentials
  (keyring service "pdf2epub"; never stored in config.toml)

Spend-safe workflow
  pdf2epub doctor
  pdf2epub convert book.pdf --report-only
  pdf2epub convert book.pdf -o book.epub --max-tier2-pages 100
```
