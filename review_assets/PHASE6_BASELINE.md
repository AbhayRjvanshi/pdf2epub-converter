# Phase 6 — M3b Architecture Note and Baseline Report

Date: 2026-10-14
Commit: `f17fe2f` (Phase 5) — tests written against this unchanged state
Scope: test-only. No production code was modified.

---

## 1. Architecture map — the actual M3b production path

```
extract_images (tier1_classifier.py:1151)
  │
  ├── Source is core format (png/jpeg/jpg/gif) + core colorspace (gray/RGB)
  │   → byte-identical passthrough (no re-encoding, no format change)
  │
  ├── Source is non-core format (jpx/bmp/tiff/webp) OR non-core colorspace (CMYK/indexed)
  │   → _transcode_to_core(data) at line 974
  │     → PyMuPDF decode → colorspace convert if needed → pix.tobytes("png")
  │     → ALWAYS produces PNG (never JPEG)
  │     → on decode failure: returns None → caller drops image with diagnostic
  │
  └── ImageElement created with ext + mime_type from the source or transcode
      → spooled to disk or held in memory
      → packaged by build_epub_publication (packaging_and_validation.py:567)
        → epub.EpubImage written as-is (no further format conversion)
```

### M3a boundary (separate, unchanged)

```
_embed_visual_page (driver.py:~260) — M3a path for vision-bypassed scanned pages
  → render page to PNG
  → encode both PNG and JPEG q90
  → keep the smaller (measured eligibility)
  → alpha-bearing or encoder failure → PNG
```

M3a and M3b are **separate code paths with separate entry points**.
M3a operates on full-page rendered rasters; M3b operates on original
embedded images extracted from PDF image blocks. No code shared between
the two paths makes format decisions.

### Hidden lossy-path search (grep across the entire engine)

- `jpg_quality` appears only in `driver.py:297` (the M3a page-raster path)
- `tobytes("jpeg")` appears only in `driver.py:297` (same M3a path)
- No environment variable, config option, CLI flag, or cached decision
  can alter the embedded-image output format
- `_transcode_to_core` has no runtime-configurable output format
- The packaging layer (`build_epup_publication`) has no image format
  selection logic — it packages whatever `ImageElement` carries

**Conclusion: no hidden lossy authorization path exists for embedded
images. The current implementation already satisfies the M3b policy.**

## 2. Baseline results

Full offline suite at the Phase 5 commit:
**757 passed, 23 skipped, 0 failed** (86.5s)

The 13 new M3b policy tests all pass against the unchanged code.
This is the expected and correct result: the current implementation
already behaves safely (lossless-only for embedded images). The tests
are regression guards for the future, not evidence of a policy gap.

### Per-requirement baseline

| # | Requirement | Test | Result | Explanation |
|---|---|---|---|---|
| 1 | Default preservation | `test_embedded_image_output_is_png_not_jpeg`, `test_transcode_to_core_produces_only_png`, `test_transcode_failure_drops_not_falls_back_to_lossy` | **PASS** (3 tests) | `_transcode_to_core` always produces PNG; core-format sources pass through byte-identical; decode failure drops with diagnostic, never a lossy fallback |
| 2 | Classifier prohibition | `test_no_feature_classifier_in_extraction_path`, `test_no_classifier_functions_exist_in_production` | **PASS** (2 tests) | No classifier code exists in the production extraction path; the rejected rules A/B/C are not referenced in any engine file |
| 3 | Alpha preservation | `test_alpha_bearing_composite_stays_png`, `test_transcode_preserves_no_alpha_when_source_has_none` | **PASS** (2 tests) | SMask composites stay PNG with alpha; opaque sources stay opaque; no alpha is silently added or removed |
| 4 | Size fallback | `test_size_fallback_contract_documented` | **PASS** (1 test) | Contract test: `_transcode_to_core` produces the lossless PNG that IS the size baseline. No exception mechanism exists to test a JPEG candidate against it |
| 5 | Fidelity fallback | `test_fidelity_fallback_contract_documented` | **PASS** (1 test) | Contract test: no lossy candidate is ever produced, so there is nothing to gate or fall back from |
| 6 | Exception isolation | `test_no_env_var_or_config_enables_lossy_transcode` | **PASS** (1 test) | `_transcode_to_core` hardcodes PNG output; no environment variable or configuration setting can alter it |
| 7 | Stable identity | `test_image_dedup_uses_content_hash_not_dimensions` | **PASS** (1 test) | Two images with identical dimensions but different content produce two separate packaged assets (content-hash dedup, not dimension dedup) |
| 8 | M3a regression | `test_m3a_page_raster_optimization_unchanged` + existing `test_vision_raster_encoding.py` (4 tests) | **PASS** (5 tests total) | The M3a path still uses measured eligibility (encode both, keep smaller); JPEG encoding for eligible page rasters is unchanged |
| 9 | Packaging integrity | `test_packaging_references_correct_images` | **PASS** (1 test) | End-to-end: structural check passes; every XHTML image reference resolves to a real EPUB asset |

### One test correction (recorded honestly)

`test_image_dedup_uses_content_hash_not_dimensions` initially failed
because the test fixture created a textless page, which routed to the
M3a vision path (single page raster) instead of the Tier 1 extraction
path (separate embedded images). The test was corrected to include
body text on the page, ensuring Tier 1 routing. This was a **test
design issue, not a policy violation** — the original test assumed
a routing behavior that doesn't match the actual architecture.

## 3. Coverage gaps and deferred requirements

| Requirement | Status | Notes |
|---|---|---|
| 4 (size fallback) | **Contract documented** | No exception mechanism exists; the contract (packaged PNG bytes as baseline, JPEG must be strictly smaller) is tested at the unit level and specified for future implementation |
| 5 (fidelity fallback) | **Contract documented** | No lossy candidate is ever produced; no fidelity gate is needed until an exception mechanism creates candidates to gate |
| 6 (exception isolation) | **Current state tested** | No env/config/flag bypasses the default; future isolation testing requires an approved exception API which does not exist |
| 7 (stable identity) | **Content-hash dedup tested** | xref identity and approval matching are future-facing (deferred with the exception mechanism); content-hash dedup is the current mechanism and is tested |

## 4. Phase 6 exit checklist

| Criterion | Status |
|---|---|
| M3b production path traced and documented | ✓ Section 1 above |
| Fixtures cover opaque, alpha, fine detail, and failure cases | ✓ Inline fixtures in the test file |
| Default preservation and classifier prohibition tested | ✓ Tests 1–6 (6 tests) |
| Size/fidelity fallbacks tested where interfaces exist | ✓ Contract tests (2 tests) |
| Identity and exception-isolation requirements documented | ✓ Tests 6–7 + gaps in Section 3 |
| M3a regression tests run | ✓ Test 8 + existing suite (5 tests) |
| EPUB packaging integrity tested | ✓ Test 9 |
| All baseline results recorded with failures classified | ✓ Section 2 (all pass; one test correction recorded) |
| Diff contains no unauthorized production changes | ✓ Test file only |
| Test-only work committed on the review branch | ✓ (this commit) |
