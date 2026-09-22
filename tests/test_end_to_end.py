"""End-to-end driver tests: real PDFs in, real EPUBs out.

Covers the failure modes that actually happen in production runs - encrypted
files, textless scans, headingless documents, ragged model output, missing
validators - and the scale behaviour that decides whether a 500 page book
converts or dies.
"""

import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

try:
    import resource  # Unix-only; used solely by the gated 500-page test below
except ImportError:  # pragma: no cover - exercised on Windows CI
    resource = None

import pytest
from ebooklib import epub

import confidence_router as cr
import main as driver
import make_fixtures as mf
import packaging_and_validation as pk
import tier1_classifier as t1

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


# ---------------------------------------------------------------------------
# Validator gating
# ---------------------------------------------------------------------------

STRICT_VAL = os.getenv("REQUIRE_EPUBCHECK", "0") == "1"
HAS_EPUBCHECK = shutil.which("epubcheck") is not None
STRICT_ACE = os.getenv("REQUIRE_ACE", "0") == "1"
HAS_ACE = shutil.which("ace") is not None
RUN_SLOW = os.getenv("RUN_SLOW_TESTS", "0") == "1"
HAS_RESOURCE = resource is not None  # Unix-only; no Windows equivalent used here


def _run(pdf, out, **kw):
    kw.setdefault("llm_adapter", None)
    kw.setdefault("verbose", False)
    kw.setdefault("cache_dir", str(Path(out).parent / "cache"))
    return driver.run_pipeline(str(pdf), str(out), **kw)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_clean_book_converts_end_to_end(fixture_pdfs, tmp_path):
    out = tmp_path / "book.epub"
    result = _run(fixture_pdfs["clean_book"], out)

    assert result["success"] is True
    assert out.exists()
    assert result["routing"] == {"tier1": 4, "tier2_digest": 1, "tier2_vision": 1}
    build = result["build"]
    assert len(build.chapters) == 2
    assert build.welded_pairs == 1
    assert build.stripped_furniture == ["a test publication"]


def test_pdf_metadata_supplies_title_and_author(fixture_pdfs, tmp_path):
    out = tmp_path / "meta.epub"
    _run(fixture_pdfs["clean_book"], out)
    book = epub.read_epub(str(out))
    assert book.get_metadata("DC", "title")[0][0] == "Fixture Title"
    assert book.get_metadata("DC", "creator")[0][0] == "Fixture Author"


def test_explicit_title_overrides_pdf_metadata(fixture_pdfs, tmp_path):
    out = tmp_path / "t.epub"
    _run(fixture_pdfs["clean_book"], out, title="My Own Title")
    book = epub.read_epub(str(out))
    assert book.get_metadata("DC", "title")[0][0] == "My Own Title"


def test_content_survives_the_round_trip(fixture_pdfs, tmp_path):
    out = tmp_path / "rt.epub"
    _run(fixture_pdfs["clean_book"], out)
    with zipfile.ZipFile(out) as zf:
        body = "".join(
            zf.read(n).decode("utf-8")
            for n in zf.namelist()
            if n.endswith(".xhtml")
        )
    assert "paying reader." in body                 # long paragraph intact
    assert "hyphenation" in body                    # soft hyphen rejoined
    assert "<strong>emphatic</strong>" in body      # inline emphasis
    assert "<pre>" in body                          # code listing
    assert "A Test Publication" not in body         # running header stripped
    # The welded sentence must be contiguous, not split across two <p>.
    assert "announces a new paragraph that does not exist." in body


def test_images_are_packaged_with_alt_text(fixture_pdfs, tmp_path):
    out = tmp_path / "img.epub"
    _run(fixture_pdfs["clean_book"], out)
    with zipfile.ZipFile(out) as zf:
        images = [n for n in zf.namelist() if n.startswith("EPUB/images/")]
        body = "".join(
            zf.read(n).decode() for n in zf.namelist() if n.endswith(".xhtml")
        )
    # One captioned figure from Tier 1, plus the fixture's image-only page
    # (offline mode bypasses OCR for it and embeds the raster directly).
    assert len(images) == 2
    assert 'alt="Figure 1' in body
    assert "image-only page" in body


def test_navigation_is_structural_not_paginated(fixture_pdfs, tmp_path):
    out = tmp_path / "nav.epub"
    _run(fixture_pdfs["clean_book"], out)
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
    assert "Chapter One: Beginnings" in nav
    assert "A Subsection Within One" in nav   # nested entry with an anchor
    assert "#sec" in nav
    assert "Page 1" not in nav


# ---------------------------------------------------------------------------
# Edge-case documents
# ---------------------------------------------------------------------------


def test_document_without_headings_yields_one_chapter(fixture_pdfs, tmp_path):
    out = tmp_path / "nh.epub"
    result = _run(fixture_pdfs["no_heading"], out)
    assert result["success"]
    assert len(result["build"].chapters) == 1


def test_fully_scanned_document_does_not_crash(fixture_pdfs, tmp_path):
    """No text layer anywhere: the font profiler must not abort the run.

    Offline (no provider configured), OCR is impossible, so the page must be
    embedded as a real raster image rather than a text placeholder that
    silently drops the picture - and that raster must actually be written
    into the EPUB container, not just referenced (a dangling reference is
    EPUBCheck RSC-007).
    """
    out = tmp_path / "scan.epub"
    result = _run(fixture_pdfs["scanned"], out)
    assert out.exists()
    assert result["routing"]["tier2_vision"] == 1
    assert result["tier2_bypassed"] == 1
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        images = [n for n in names if "images/" in n]
        assert images, "scanned page's raster was never written into the container"
        body = "".join(zf.read(n).decode() for n in names if n.endswith(".xhtml"))
    assert "<img" in body
    assert "image-only page" in body  # honest alt text, not silent emptiness


def test_encrypted_pdf_fails_with_a_clear_message(tmp_path):
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 100), "secret content here")
    locked = tmp_path / "locked.pdf"
    src.save(
        str(locked),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    src.close()
    with pytest.raises(RuntimeError, match="password protected"):
        _run(locked, tmp_path / "x.epub")


def test_corrupt_file_is_rejected(tmp_path):
    junk = tmp_path / "corrupt.pdf"
    junk.write_bytes(b"%PDF-1.7\nnot actually a pdf body")
    with pytest.raises(Exception):
        _run(junk, tmp_path / "x.epub")


def test_document_with_no_extractable_content_fails_loudly(fixture_pdfs, tmp_path,
                                                            monkeypatch):
    """Silent empty output is worse than an error; the driver must say so."""
    monkeypatch.setattr(
        driver, "parse_xhtml_to_stream_elements", lambda *a, **k: []
    )
    monkeypatch.setattr(
        driver.tier1_classifier, "build_page_stream", lambda *a, **k: []
    )
    # The dual-policy image bypass is a third, independent content source
    # (Problem 4) - it must also be neutralised for this to genuinely exercise
    # "nothing was extracted anywhere", not just the two XHTML-producing paths.
    monkeypatch.setattr(driver, "_embed_visual_page", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="No content extracted"):
        _run(fixture_pdfs["clean_book"], tmp_path / "x.epub")


def test_blank_pages_produce_no_phantom_content(tmp_path):
    doc = fitz.open()
    doc.new_page(width=mf.PAGE_W, height=mf.PAGE_H)  # blank
    p = doc.new_page(width=mf.PAGE_W, height=mf.PAGE_H)
    mf.put_heading(p, mf.MARGIN_X, 90.0, "Only Chapter", 17.0)
    mf.put_paragraph(p, mf.MARGIN_X, 130.0, mf.COL_W,
                     mf.greedy_wrap(mf.FIVE_LINE_TEXT, mf.COL_W))
    src = tmp_path / "blank.pdf"
    doc.save(str(src))
    doc.close()
    result = _run(src, tmp_path / "blank.epub")
    assert result["success"]


def test_output_directory_is_created(fixture_pdfs, tmp_path):
    out = tmp_path / "deep" / "nested" / "book.epub"
    _run(fixture_pdfs["single_column"], out)
    assert out.exists()


def test_report_only_writes_nothing(fixture_pdfs, tmp_path, capsys):
    out = tmp_path / "never.epub"
    result = _run(fixture_pdfs["clean_book"], out, report_only=True, verbose=True)
    assert result["success"]
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "tier2-vision" in printed and "score" in printed


def test_skip_validation_short_circuits(fixture_pdfs, tmp_path):
    out = tmp_path / "nv.epub"
    result = _run(fixture_pdfs["single_column"], out, skip_validation=True)
    assert result["success"]
    assert "validation" not in result


# ---------------------------------------------------------------------------
# Tier 2 integration and stream ordering
# ---------------------------------------------------------------------------


def test_tier1_and_tier2_pages_keep_document_order(fixture_pdfs, tmp_path):
    out = tmp_path / "order.epub"
    result = _run(fixture_pdfs["clean_book"], out)
    pages = [e.page_num for e in result["build"].clean_stream]
    assert pages == sorted(pages)


def test_ragged_model_output_does_not_lose_pages(fixture_pdfs, tmp_path):
    """A model that returns too few pages must not drop content or crash."""
    import json

    calls = {"n": 0}

    def stingy(system_prompt, payload, image_b64=None):
        calls["n"] += 1
        return json.dumps({"xhtml_pages": ["<p>partial</p>"]})

    out = tmp_path / "ragged.epub"
    result = _run(fixture_pdfs["clean_book"], out, llm_adapter=stingy, batch_size=4)
    assert result["success"]
    assert calls["n"] >= 1


def test_model_returning_broken_xhtml_is_repaired(fixture_pdfs, tmp_path):
    import json

    def sloppy(system_prompt, payload, image_b64=None):
        return json.dumps(
            {"xhtml_pages": ["```xml\n<p>Q&A <strong>unclosed</p>\n```"] * 4}
        )

    out = tmp_path / "sloppy.epub"
    result = _run(fixture_pdfs["clean_book"], out, llm_adapter=sloppy, batch_size=4)
    assert result["success"]
    with zipfile.ZipFile(out) as zf:
        body = "".join(
            zf.read(n).decode() for n in zf.namelist() if n.endswith(".xhtml")
        )
    assert "```" not in body
    assert "&amp;" in body


def test_cache_makes_a_second_run_free(fixture_pdfs, tmp_path):
    import json

    calls = {"n": 0}

    def counting(system_prompt, payload, image_b64=None):
        calls["n"] += 1
        return json.dumps({"xhtml_pages": ["<p>x</p>"] * 4})

    cache = tmp_path / "cache"
    _run(fixture_pdfs["clean_book"], tmp_path / "a.epub",
         llm_adapter=counting, cache_dir=str(cache))
    first = calls["n"]
    _run(fixture_pdfs["clean_book"], tmp_path / "b.epub",
         llm_adapter=counting, cache_dir=str(cache))
    assert calls["n"] == first, "second run should be served entirely from cache"


# ---------------------------------------------------------------------------
# Validation and self-repair
# ---------------------------------------------------------------------------


def test_missing_validators_do_not_fail_the_run(fixture_pdfs, tmp_path, monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(pk.subprocess, "run", missing)
    result = _run(fixture_pdfs["single_column"], tmp_path / "nv.epub")
    assert result["success"]
    assert result["validation"].epubcheck_available is False


def test_repair_loop_runs_and_gives_up_cleanly(fixture_pdfs, tmp_path, monkeypatch):
    """A validator that never passes must terminate, not spin."""
    attempts = {"n": 0}
    real_validate = pk.DualValidator.validate

    def always_failing(self, epub_path):
        attempts["n"] += 1
        report = real_validate(self, epub_path)
        report.structural_passed = False
        report.structural_errors = [
            {"file": "chapter_001.xhtml", "message": "synthetic", "severity": "ERROR"}
        ]
        return report

    monkeypatch.setattr(pk.DualValidator, "validate", always_failing)
    result = _run(fixture_pdfs["single_column"], tmp_path / "r.epub",
                  max_repair_attempts=2)
    assert result["success"] is False
    assert attempts["n"] == 3  # initial pass plus two repair attempts
    assert (tmp_path / "r.epub").exists()  # best effort output is still written


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_returns_zero_on_success(fixture_pdfs, tmp_path):
    code = driver.main([
        fixture_pdfs["single_column"], "-o", str(tmp_path / "cli.epub"),
        "--provider", "none", "--cache-dir", str(tmp_path / "c"), "--quiet",
    ])
    assert code == 0
    assert (tmp_path / "cli.epub").exists()


def test_cli_returns_two_for_a_missing_input(tmp_path):
    assert driver.main([str(tmp_path / "nope.pdf"), "--provider", "none"]) == 2


def test_cli_returns_one_on_a_fatal_error(tmp_path):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    code = driver.main([
        str(junk), "-o", str(tmp_path / "x.epub"), "--provider", "none", "--quiet",
    ])
    assert code == 1


def test_cli_report_only(fixture_pdfs, tmp_path, capsys):
    code = driver.main([
        fixture_pdfs["clean_book"], "--report-only", "--provider", "none",
        "-o", str(tmp_path / "unused.epub"),
    ])
    assert code == 0
    assert "tier1" in capsys.readouterr().out


def test_unknown_provider_falls_back_to_offline_mode():
    assert driver.create_llm_client_adapter("nonsense", "m") is None


# ---------------------------------------------------------------------------
# Real EPUBCheck conformance
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_EPUBCHECK and not STRICT_VAL,
    reason="epubcheck not found in PATH (set REQUIRE_EPUBCHECK=1 to force failure)",
)
def test_epubcheck_conformance(fixture_pdfs, tmp_path):
    if not HAS_EPUBCHECK and STRICT_VAL:
        pytest.fail("REQUIRE_EPUBCHECK=1 is set, but 'epubcheck' was not found in PATH.")

    out = tmp_path / "conform.epub"
    result = _run(fixture_pdfs["clean_book"], out)
    report = result["validation"]
    assert report.epubcheck_available is True
    assert report.epubcheck_passed is True, report.raw_logs
    assert report.epubcheck_errors == 0


@pytest.mark.skipif(
    not HAS_EPUBCHECK and not STRICT_VAL,
    reason="epubcheck not found in PATH (set REQUIRE_EPUBCHECK=1 to force failure)",
)
@pytest.mark.parametrize("fixture", ["single_column", "no_heading", "scanned"])
def test_epubcheck_conformance_across_fixtures(fixture, fixture_pdfs, tmp_path):
    if not HAS_EPUBCHECK and STRICT_VAL:
        pytest.fail("REQUIRE_EPUBCHECK=1 is set, but 'epubcheck' was not found in PATH.")
    result = _run(fixture_pdfs[fixture], tmp_path / f"{fixture}.epub")
    assert result["validation"].epubcheck_passed, result["validation"].raw_logs


# ---------------------------------------------------------------------------
# Real Ace by DAISY conformance
#
# parse_ace_violations() itself is unit-tested against synthetic/mocked JSON
# elsewhere (test_packaging.py) with zero external dependencies. Those tests
# only prove the Python parsing logic is internally consistent - they cannot
# catch a real schema change in a future Ace release. This test is the other
# half of the hybrid strategy: it runs the actual binary and would fail the
# moment Ace's report shape drifts out from under the parser.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_ACE and not STRICT_ACE,
    reason="ace not found in PATH (set REQUIRE_ACE=1 to force failure)",
)
def test_ace_conformance_real_binary(fixture_pdfs, tmp_path):
    if not HAS_ACE and STRICT_ACE:
        pytest.fail("REQUIRE_ACE=1 is set, but 'ace' was not found in PATH.")

    out = tmp_path / "ace_conform.epub"
    result = _run(fixture_pdfs["clean_book"], out)
    report = result["validation"]
    assert report.ace_available is True
    assert report.ace_passed is True, report.raw_logs
    assert report.ace_violations.get("critical", 0) == 0
    assert report.ace_violations.get("serious", 0) == 0


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def large_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("large") / "large.pdf"
    return mf.build_large_book(path, pages=120)


def test_font_profile_samples_instead_of_reading_every_page(large_pdf):
    doc = fitz.open(large_pdf)
    profile = t1.DocumentFontProfile.build(doc, max_sample_pages=20)
    assert profile.sampled_pages == 20
    assert profile.body_size == pytest.approx(10.0)
    full = t1.DocumentFontProfile.build(doc)
    assert profile.body_size == full.body_size
    assert profile.line_height == full.line_height
    doc.close()


def test_triage_of_a_long_document_holds_no_payloads(large_pdf):
    doc = fitz.open(large_pdf)
    reports = cr.route_document(doc)
    assert len(reports) == 120
    assert all(r.raster_bytes is None for r in reports)
    assert sum(1 for r in reports if r.is_tier1) == 120  # clean book, zero API cost
    doc.close()


@pytest.mark.skipif(
    not HAS_RESOURCE, reason="'resource' module not available on this platform"
)
def test_long_document_converts_within_budget(large_pdf, tmp_path):
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    result = _run(large_pdf, tmp_path / "large.epub")
    elapsed = time.monotonic() - started
    growth_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024

    assert result["success"]
    assert elapsed < 90, f"120 pages took {elapsed:.1f}s"
    assert growth_mb < 400, f"resident set grew {growth_mb:.0f}MB"
    assert len(result["build"].chapters) == 5  # a heading every 25 pages


def test_repeated_images_are_stored_once(large_pdf, tmp_path):
    """The same logo on every tenth page must not be packaged twelve times."""
    out = tmp_path / "dedup.epub"
    result = _run(large_pdf, out)
    assert result["build"].a11y.image_count == 12
    with zipfile.ZipFile(out) as zf:
        stored = [n for n in zf.namelist() if n.startswith("EPUB/images/")]
    assert len(stored) == 1


def test_spooled_images_are_not_held_in_memory(large_pdf, tmp_path):
    import tempfile

    with tempfile.TemporaryDirectory() as spool:
        doc = fitz.open(large_pdf)
        profile = t1.DocumentFontProfile.build(doc)
        stream = t1.build_page_stream(doc[0], profile, 0, spool_dir=spool)
        images = [e for e in stream if e.image_data]
        assert images
        for e in images:
            assert e.image_data.image_bytes == b""
            assert Path(e.image_data.source_path).exists()
            assert e.image_data.load_bytes()[:4] == b"\x89PNG"
        doc.close()


def test_chapter_files_scale_with_headings_not_pages(large_pdf, tmp_path):
    """Regression against page-as-a-file packaging."""
    out = tmp_path / "chapters.epub"
    _run(large_pdf, out)
    with zipfile.ZipFile(out) as zf:
        chapters = [n for n in zf.namelist() if "chapter_" in n]
    assert len(chapters) == 5
    assert len(chapters) < 120


@pytest.mark.skipif(not RUN_SLOW, reason="set RUN_SLOW_TESTS=1 for the 500 page run")
@pytest.mark.skipif(
    not HAS_RESOURCE, reason="'resource' module not available on this platform"
)
def test_five_hundred_page_document(tmp_path_factory, tmp_path):
    path = tmp_path_factory.mktemp("huge") / "huge.pdf"
    mf.build_large_book(path, pages=500)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    result = _run(path, tmp_path / "huge.epub")
    elapsed = time.monotonic() - started
    growth_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024

    assert result["success"]
    assert result["element_count"] > 2000
    assert len(result["build"].chapters) == 20
    assert elapsed < 300, f"500 pages took {elapsed:.1f}s"
    assert growth_mb < 800, f"resident set grew {growth_mb:.0f}MB"
