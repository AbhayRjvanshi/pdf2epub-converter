# Round 3 M0b — Image Inventory and Size Attribution (WS-1)

Date: 2026-10-13
Scope: **measurement only — no production encoding behavior changed in
this milestone.** The committed tool is `scripts/image_inventory.py`;
every number below is reproducible with it (commands at the end). The
baseline EPUBs are kept outside the repository, identified by hash.

## Frozen baselines

* Engine commit: `c6ecb21` ("Calibrate the long-document memory budget
  per platform"), working tree clean at generation time.
* CI: run #3 green, **14/14 jobs** — 12 test-matrix legs
  (Linux/macOS/Windows x Python 3.10-3.13), clean-install-from-wheel,
  real EPUBCheck 5.1.0 conformance (hard-fail mode).
* Toolchain: PyMuPDF 1.28.2, Python 3.10 (.venv), EPUBCheck 5.1.0
  (CI job, pinned; also installed locally), Ace by DAISY 1.4.6 (local).

| Document | Role | Pages | Source SHA-256 | Baseline EPUB bytes | Baseline EPUB SHA-256 |
|---|---|---|---|---|---|
| THE FLOWER GARDEN (Monkey Pen) | control case | 32 | `e91fcea3b9d46b1432624d78d257973a53b53417a578698ddc4500b1fe075015` | 10,543,872 | `c194b312ba5ed949692832b624382a1dc95fe7fe119192818a606a21ab386eac` |
| Artificial_Intelligence_Projects | frozen reference | 6 | `369b95fe20c4511b2bb29a6c3a66ee7fe561991273b5320df65461544aa9638d` | 111,393 | `a3f5aae19a5bad783f629e5776bf1e26e8a3078b70b821c01d620b1f3eab0e8e` |
| Play, dance, Music recreation…therapies (compressed) | C1 scanned corpus doc — **M3a target** | 74 | `d00068d2f6f2d4e2a7ca5a07e5fc90231d0b99e1fb8831fc52b8a939db695b30` | 86,839,707 | `d8f6c4ccd5c924d6233a61948002bba775a5abd0f15c2ab7ed26fd3ae1557469` |
| Hands-On Generative AI (Z-Library) | JPX corpus doc — **M3b target** | 419 | `20ca8b5967e51d603d4d2a9ab47c2d9524882ec4f8ab9fa912da21486003b6a7` | 51,763,248 | `4aeba860ba330625a26213dee69efeadf5824fb9e0b2a9fd80b1f5c1e94c53fd` |

## Method (execution control #2: traceable attribution)

* Every packaged asset is joined back to its PDF origin by **xref +
  bounding-box placement overlap**, never by pixel dimensions —
  dimensions collide in real books (every full-page illustration in
  the Flower Garden is ~820x1060).
* Ambiguous joins (runner-up overlap >= 90% of best) are flagged
  `ambiguous: true`, never resolved by force.
* Unmatched assets are recorded as `unmatched`.
* Attribution classes (behavior, not image-content guesses):
  `rendered-page-raster` (vision-embedded scan page), `mask-composite`
  (source soft mask composited into alpha), `mask-fallback` (mask
  present, compositing failed, opaque base kept — transparency lost),
  `transcoded` (non-core source format or colorspace, re-encoded at
  extraction), `passthrough` (output bytes byte-identical to source),
  `re-encoded` (same-core format, bytes differ), `join-suspect`
  (placement matched a page-filling artwork but dimensions are
  incompatible — recorded, class withheld).
* Colorspace semantics: the dict-block/`extract_image` colorspace is a
  **component count** when an int, identical to the extraction gate's
  own constants (`_CS_GRAY=1`, `_CS_RGB=3`; 4 = CMYK). Verified
  against decoded pixels after an initial misreading (int 3 is not
  `fitz.CS_CMYK`); all Flower Garden sources decode `DeviceRGB`.

## Results

### THE FLOWER GARDEN — 35 assets, 10,575,922 packaged image bytes

| class | assets | out bytes | src bytes |
|---|---|---|---|
| passthrough | 27 | 6,074,709 | 6,074,709 |
| mask-composite | 5 | 4,446,821 | 840,700 |
| unmatched | 1 | 53,777 | — |
| join-suspect | 2 | 615 | (suspect join) |

Unmatched: 1, ambiguous joins: 0, join-relevant dimension mismatches: 2
(both are the `join-suspect` class). The 1 unmatched asset is a 612x701
alpha PNG on page 31 with no xref-backed placement (transparency-group
rasterization); the 2 join-suspects are 43x44 / 36x37 alpha icons
whose bboxes sit inside page-filling artwork.

**Finding: the Round 1 size growth is fully attributed.** The five
masked illustrations account for the entire +3.6 MB (840,700 bytes of
sources -> 4,446,821 bytes of composited PNG). The 27 opaque assets are
byte-identical RGB JPEG passthroughs — already optimal, and re-encoding
them is prohibited by the Round 3 policy (Task 2.2). PNG is the only
EPUB-3 core raster format carrying alpha, so the composites cannot
leave PNG without flattening, which the policy forbids.
**The correct optimization result for this book is ~0% reduction —
it is the control case, not a failure.**

### C1 scanned doc (Play, dance, Music therapies) — 74 assets

| class | assets | out bytes | src bytes |
|---|---|---|---|
| rendered-page-raster | 74 | 89,568,341 | 15,425,509 |

Unmatched: 0, ambiguous: 0, join-relevant mismatches: 0.

**Finding: the M3a class, fully quantified.** Every page is a
vision-embedded rendered PNG raster; the underlying sources are
full-page JPEG scans totaling 15.4 MB — a **5.8x inflation**. The
output (86.84 MB) matches the corpus record's 86.8 MB baseline: no
cross-round size regression in this class. JPEG-encoding these rasters
at q90 is the approved M3a change; measured savings will be reported
after implementation, not promised in advance.

*Backlog note (recorded, out of M3a scope):* these pages are single
full-page JPEG scans — a future policy could package the source JPEG
directly (byte-identical passthrough, ~15.4 MB total, zero quality
loss) instead of re-rendering the page. It needs its own
placement/rotation/CropBox evidence rules and is recorded for the
routing/policy backlog, not implemented here.

### Hands-On Generative AI — 202 assets

| class | assets | out bytes | src bytes |
|---|---|---|---|
| transcoded | 180 | 47,830,312 | 3,537,937 |
| mask-composite | 3 | 3,260,146 | 322,377 |
| rendered-page-raster | 8 | 865,851 | — |
| passthrough | 11 | 116,785 | 116,785 |

Unmatched: 0, ambiguous: 0, join-relevant mismatches: 0.

**Finding: the M3b class, fully quantified.** All 180 transcoded
sources are JPX (179 RGB, 1 gray) re-encoded as PNG at extraction — a
**13.5x inflation** carrying 93% of this book's 51.8 MB EPUB. The
three-outcome classifier (photographic / line-art / uncertain-lossless)
decides per asset how much of this is recoverable; thresholds will be
pinned against these real figures, per the Round 3 plan.

### Artificial_Intelligence_Projects (reference) — 1 asset

1 rendered-page raster, 125,022 bytes; the structural reference
metrics of this document are frozen in the Round 2 record.

## Verified facts vs. guesses

Verified facts: asset counts, classes, formats, byte deltas, colorspace
component counts, alpha presence, dimension matches, source and EPUB
hashes, EPUB sizes.
**Not claimed here:** photographic-vs-line-art classification (M3b,
with pinned thresholds), visual quality of any encoding (WS-3/WS-4
gates), reader rendering behavior.

## Instrument corrections, recorded honestly

1. The plan-phase inventory joined by dimensions and produced two
   false matches (tiny icons "growing" from full-page JPEGs); the
   xref/bbox join exposes them as `join-suspect` and they are excluded
   from attribution.
2. An initial colorspace misreading (int 3 read as `fitz.CS_CMYK`)
   briefly classified the 27 RGB passthroughs as "transcoded"; corrected
   against the gate's constants and verified by decoding the pixels
   (`DeviceRGB`, byte-identical passthrough).
3. The dimension-mismatch counter originally flagged C1's 74 rendered
   rasters; rendered rasters legitimately differ in resolution from
   their backing scans, so the counter now applies only where the join
   feeds classification.

## Commands (reproducibility)

```
# offline, structural validation only; baselines land in <dir>
.venv\Scripts\python.exe scripts\image_inventory.py <source.pdf> --out-dir <dir>
# writes <stem>_inventory.json (per-asset records) and keeps the
# baseline EPUB next to it; prints the class table and totals.
```
