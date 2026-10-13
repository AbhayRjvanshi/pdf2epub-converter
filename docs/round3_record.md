# Round 3 Record — Image efficiency, fidelity and conversion-quality instrumentation

Workstreams land as separate committed milestones; this record grows
with the round and is consolidated at M6. All numbers are measured at
the stated commits with the stated tools; every milestone lists its
reproduction commands. Dates: 2026-10-13/14.

## M0 — Release boundary: CI verification (complete)

* Run #1 (`aae3e00`) failed workflow validation with **zero jobs
  created**: `${{ env.* }}` is not an available context in a GitHub
  Actions job `name:`. Fixed by hardcoding the pinned version in the
  job name (`dee9e43`), with an in-file comment so it cannot silently
  regress.
* Run #2 executed all 14 jobs (the parse/execute gate passed) and
  failed exactly two legs — `macos-latest` Python 3.10 and 3.13 — on
  exactly one test: `test_long_document_converts_within_budget`
  measured 416 MB / 480 MB of `ru_maxrss` growth against a
  Linux-calibrated 400 MB budget. Every leg runs the identical
  `pymupdf-1.28.2 cp310-abi3` wheel: test calibration, not a
  dependency issue. Fixed with a platform-aware budget (`c6ecb21`):
  Linux keeps 400 MB; macOS gets an evidence-based 600 MB (measured
  480 MB + 25%). *(Corrected below: the macOS figures in this
  paragraph were kilobytes mislabelled as megabytes, and this
  platform-specific budget was based on an invalid interpretation.)*
* Run #3 (`c6ecb21`): **14/14 green** — the workflow's first complete
  execution ever, including the clean-install-from-wheel job and the
  real pinned EPUBCheck 5.1.0 conformance job (hard-fail mode).
* Run #4 (`5dd3135`, M0b): 14/14 green.
* Run #5 (`ba935e9`, M3a): 13/14 green; `macos-latest` Python 3.13
  failed the same gate at "624 MB" — a +30% swing on a code path M3a
  never touches. The investigate-don't-ratchet rule was applied and
  the investigation overturned the run-#2 calibration:

  **M0 correction — mislabelled units and a flawed measurement
  design.** Darwin reports `ru_maxrss` in **bytes** (BSD
  getrusage(2)); Linux reports **KiB** (getrusage(2)). The gate
  divided by 1024 on both platforms, so the "416 / 480 / 624 MB"
  macOS figures were kilobytes — real peak-deltas of roughly
  0.4–0.6 MB. The gate also subtracted two readings of one
  long-lived pytest process's historical peak, so it measured how
  far this conversion overshot the session's existing high-water
  mark — allocator noise, not the conversion's footprint. The
  platform-split budget of `c6ecb21` was therefore based on an
  invalid interpretation: it passed runs #3/#4 by luck and failed
  #5 by noise.

  **The corrected gate**: the 120-page conversion now runs in a
  fresh subprocess (`tests/memprobe.py`) that reports its **own
  total peak** with platform-normalized units (Darwin bytes/1024²,
  Linux KiB/1024 — both conventions pinned by unit tests), no
  subtraction anywhere, under a single **provisional budget of
  400 MiB on every platform**. The elapsed-time guard (< 90 s) is
  preserved. The budget is explicitly provisional: the first CI run
  supplies the missing fresh-process peak measurement and the value
  is tightened once from that evidence — the 95 MB peak-RSS figure
  for a 500-page book is context, not proof for this fixture.
  Gate-verification tests pin that the probe reports a plausible
  peak of its own, that a failed child conversion propagates into a
  test failure, and that both unit conventions normalize correctly.

## M0b — Image inventory and size attribution (complete)

Committed as `5dd3135`; the full attribution report is
[round3_image_inventory.md](round3_image_inventory.md). Headlines:
the Flower Garden's +3.6 MB is entirely its five mask composites
(27 byte-identical RGB JPEG passthroughs; ~0% eligible headroom — the
control case); C1's rendered page rasters are 89.57 MB against
15.43 MB of source JPEGs (5.8x); Hands-On's 180 JPX transcodes are
47.83 MB against 3.54 MB of sources (13.5x).

## M3a — Vision-embedded scanned-page rasters (complete)

**Change** (`engine/driver.py`, `_embed_visual_page`,
`VISION_RASTER_JPEG_QUALITY = 90`): eligibility for JPEG is
**measured, not guessed** — the page render is encoded both ways and
the smaller representation is packaged. Photographic scan renders win
big under JPEG (C1); born-digital flat pages stay PNG. Alpha-bearing
rasters and encoder failures keep the lossless PNG in every branch.

The measured rule is not decoration: a JPEG-only version of this
change **regressed the reference book's vision page** from 125,022
bytes (PNG) to 202,835 bytes (q90 JPEG) — found by comparing against
the M0b-frozen baseline, fixed by making eligibility an outcome of
the size comparison, and pinned by a test whose premise (PNG smaller
on born-digital text) is asserted in-test.

**Tests** (`tests/engine/test_vision_raster_encoding.py`, 5 new,
failing-first against the PNG-only behavior):

* photographic scanned fixture -> packaged as real JPEG (SOI
  signature), manifest `media-type="image/jpeg"` matching the bytes,
  dimensions identical to the lossless render;
* born-digital text render -> PNG kept (premise measured in-test);
* alpha-bearing raster -> PNG kept (JPEG cannot carry alpha;
  flattening is forbidden by the Round 3 policy);
* simulated encoder failure -> PNG kept (a page's content must
  never be lost to an encoding attempt);
* byte-level determinism across repeated conversions.

The scanned fixture's inserted image changed from a flat square to a
deterministic photographic-like gradient (`make_gradient_png`): a
flat square legitimately stays PNG under the measured rule, so it no
longer represented the class the fixture tests.

**Regression evidence:** offline suite **743 passed / 21 skipped**
(+5 tests over the M0b state); Flower Garden integration gates **3/3**
with EPUBCheck (the control case is untouched — it has no vision
pages).

**Benchmark** (frozen M0b baselines vs this change; PyMuPDF 1.28.2,
`RASTER_DPI = 150` unchanged, encoder
`Pixmap.tobytes("jpeg", jpg_quality=90)`):

| document | metric | before (M0b) | after (M3a) | reduction |
|---|---|---|---|---|
| C1 scan (74 vision pages) | rendered rasters | 89,568,341 | 33,122,997 (JPEG) | **63.0%** |
| C1 scan | whole EPUB | 86,839,707 | 29,140,165 | **66.4%** |
| reference book | vision raster / EPUB | 125,022 / 111,393 | 125,022 / 111,392 (PNG kept) | unchanged — correct |
| C3 scan (2 pages) | whole EPUB | 0.7 MB (corpus-era figure) | 446,039 (JPEG won both) | informational |

The reference book's EPUB is byte-count-stable with its frozen
baseline (the one-byte delta is uuid/timestamp entropy in the OPF,
not content).

**Quality protocol** (per the approval conditions) — q85 vs q90
compared on three representative C1 pages (5, 37, 74: dense scanned
text, the hardest class for JPEG):

| page | PNG bytes | q90 bytes | q85 bytes | q90 max/mean abs diff (0-255) | q85 |
|---|---|---|---|---|---|
| 5 | 1,719,992 | 617,714 | 530,302 | 11 / 0.41 | 17 / 0.55 |
| 37 | 1,284,214 | 464,037 | 400,993 | 11 / 0.29 | 17 / 0.36 |
| 74 | 1,676,916 | 591,753 | 509,048 | 10 / 0.39 | 16 / 0.50 |

**Decision: q90 stands** (the approved default). q85's additional
saving is 13.9% of the already-reduced image bytes — under the
approval's own criterion ("choose q85 only if its additional savings
are material and the visual difference remains acceptable") that is
not material against max deviations of 16-17/255 vs q90's 10-11.
Side-by-side review files (reference PNG, decoded q90, decoded q85
per page) are retained with the session artifacts for human
inspection; the automated decision is recorded here so a reviewer
can overturn it with evidence.

**Validation of the real C1 artifact** (29,140,165 bytes, 74 JPEG
rasters): internal structural check PASS; EPUBCheck 5.1.0 PASS,
0 errors; Ace 1.4.6 PASS 0/0/0/0. All 74 rasters verified
dimension-identical to the lossless render.

**Not claimed:** reader-rendering verification of JPEG pages (the
standing visual-regression deferral); C3's rasters render at 150 DPI
smaller than its high-resolution source scans — pre-existing
behavior, covered by the source-passthrough backlog note in the
inventory record.

## Commands

```
# offline suite (validators unresolvable)
$env:NVIDIA_API_KEY = $null
$env:Path = <npm global bin removed>
.venv\Scripts\python.exe -m pytest

# real-book gates (EPUBCheck visible)
$env:PDF2EPUB_FLOWER_PDF = <Flower Garden PDF>
.venv\Scripts\python.exe -m pytest tests\integration

# per-asset inventory + baseline EPUB (measurement tool)
.venv\Scripts\python.exe scripts\image_inventory.py <pdf> --out-dir <dir>
```
