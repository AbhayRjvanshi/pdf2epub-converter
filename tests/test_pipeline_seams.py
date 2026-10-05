"""Phase 8: additive engine seams, all defaulted off.

S1 validator selection, S2 pipeline events, S3 cancellation and S5
precomputed routing. Every seam defaults to the previous behavior.
"""

import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - legacy alias
    import fitz

from pdf2epub.engine import confidence_router, driver
from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.engine.cancellation import CancellationToken
from pdf2epub.engine.driver import run_pipeline
from pdf2epub.engine.events import PipelineEvent


def _stub_validator(
    monkeypatch,
    *,
    epubcheck_result=(True, 0, "epubcheck-ok", False),
    ace_result=(True, {}, "ace-ok", False),
):
    validator = pk.DualValidator()
    calls = []

    monkeypatch.setattr(pk, "internal_structure_check", lambda path: [])

    def run_epubcheck(path, work_dir=None):
        calls.append("epubcheck")
        return epubcheck_result

    def run_daisy_ace(path, out_dir=None):
        calls.append("ace")
        return ace_result

    monkeypatch.setattr(validator, "run_epubcheck", run_epubcheck)
    monkeypatch.setattr(validator, "run_daisy_ace", run_daisy_ace)
    return validator, calls


def test_validators_default_runs_both_external_tools(monkeypatch):
    validator, calls = _stub_validator(monkeypatch)
    report = validator.validate("book.epub")
    assert calls == ["epubcheck", "ace"]
    assert report.disabled == []
    assert report.passed is True


def test_validators_empty_runs_only_the_internal_check(monkeypatch):
    validator, calls = _stub_validator(monkeypatch)
    report = validator.validate("book.epub", enabled=())
    assert calls == []
    assert report.disabled == ["epubcheck", "ace"]
    assert report.passed is True


def test_validators_selects_epubcheck_only(monkeypatch):
    validator, calls = _stub_validator(monkeypatch)
    report = validator.validate("book.epub", enabled=("epubcheck",))
    assert calls == ["epubcheck"]
    assert report.disabled == ["ace"]


def test_validators_selects_ace_only(monkeypatch):
    validator, calls = _stub_validator(monkeypatch)
    report = validator.validate("book.epub", enabled=("ace",))
    assert calls == ["ace"]
    assert report.disabled == ["epubcheck"]


def test_disabled_validator_failure_cannot_fail_the_run(monkeypatch):
    validator, _ = _stub_validator(
        monkeypatch, epubcheck_result=(False, 5, "broken", True)
    )
    report = validator.validate("book.epub", enabled=())
    assert report.passed is True  # EPUBCheck never ran


def test_enabled_validator_failure_does_fail_the_run(monkeypatch):
    validator, _ = _stub_validator(
        monkeypatch, epubcheck_result=(False, 2, "broken", True)
    )
    report = validator.validate("book.epub", enabled=("epubcheck",))
    assert report.passed is False
    assert report.disabled == ["ace"]


def _convert(fixture_pdfs, tmp_path, *, pdf="clean_book", out="out.epub", **kw):
    kw.setdefault("llm_adapter", None)
    kw.setdefault("verbose", False)
    kw.setdefault("skip_validation", True)
    kw.setdefault("cache_dir", str(tmp_path / "cache"))
    return run_pipeline(fixture_pdfs[pdf], str(tmp_path / out), **kw)


# -- S2: pipeline events ----------------------------------------------------

def test_events_are_emitted_and_end_with_completed(fixture_pdfs, tmp_path):
    events = []
    result = _convert(fixture_pdfs, tmp_path, event_cb=events.append)
    assert result["success"] is True
    types = [e.type for e in events]
    assert "phase_started" in types
    assert types[-1] == "completed"
    assert all(isinstance(e, PipelineEvent) for e in events)


def test_no_callback_result_is_identical(fixture_pdfs, tmp_path):
    with_cb = _convert(fixture_pdfs, tmp_path, out="a.epub", event_cb=lambda e: None)
    without = _convert(fixture_pdfs, tmp_path, out="b.epub")
    assert with_cb["success"] == without["success"]
    assert with_cb["element_count"] == without["element_count"]
    assert with_cb["routing"] == without["routing"]


def test_raising_callback_never_aborts_the_conversion(fixture_pdfs, tmp_path):
    def boom(event):
        raise RuntimeError("UI bug")

    result = _convert(fixture_pdfs, tmp_path, event_cb=boom)
    assert result["success"] is True
    assert "cancelled" not in result


def test_tier2_batch_event_fires_for_a_digest_fixture(fixture_pdfs, tmp_path):
    events = []
    result = _convert(
        fixture_pdfs, tmp_path, pdf="two_column", event_cb=events.append
    )
    assert result["success"] is True
    assert any(e.type == "tier2_batch_started" for e in events)


class _FailingReport:
    passed = False
    structural_passed = False
    structural_errors = []
    epubcheck_passed = True
    epubcheck_available = False
    epubcheck_errors = 0
    ace_passed = True
    ace_available = False
    ace_violations = {}
    disabled = []
    raw_logs = "fake validation failure"


def test_validation_repair_and_failure_events(fixture_pdfs, tmp_path, monkeypatch):
    class _FailingValidator:
        def validate(self, path, enabled=None):
            return _FailingReport()

    monkeypatch.setattr(driver, "DualValidator", _FailingValidator)
    events = []
    result = _convert(
        fixture_pdfs,
        tmp_path,
        skip_validation=False,
        max_repair_attempts=1,
        event_cb=events.append,
    )
    assert result["success"] is False
    types = [e.type for e in events]
    assert "validation_started" in types
    assert types.count("repair_started") == 1
    assert types[-1] == "failed"


# -- S3: cancellation -------------------------------------------------------

def test_cancel_before_start(fixture_pdfs, tmp_path):
    token = CancellationToken()
    token.cancel()
    result = _convert(fixture_pdfs, tmp_path, cancel_token=token)
    assert result["cancelled"] is True
    assert result["success"] is False


def test_uncancelled_token_is_identical(fixture_pdfs, tmp_path):
    result = _convert(fixture_pdfs, tmp_path, cancel_token=CancellationToken())
    assert result["success"] is True
    assert "cancelled" not in result


def test_cancel_mid_pipeline_stops_cleanly(fixture_pdfs, tmp_path):
    token = CancellationToken()

    def cancel_on_tier1(event):
        if event.type == "phase_started" and event.phase == 4:
            token.cancel()

    result = _convert(
        fixture_pdfs, tmp_path, cancel_token=token, event_cb=cancel_on_tier1
    )
    assert result.get("cancelled") is True
    assert result["success"] is False


def test_callback_exceptions_do_not_cancel(fixture_pdfs, tmp_path):
    def boom(event):
        raise RuntimeError("nope")

    result = _convert(
        fixture_pdfs, tmp_path, cancel_token=CancellationToken(), event_cb=boom
    )
    assert result["success"] is True


# -- S5: precomputed routing ------------------------------------------------

def _route(fixture_pdfs, key):
    doc = fitz.open(fixture_pdfs[key])
    try:
        return confidence_router.route_document(doc, build_payloads=False)
    finally:
        doc.close()


def test_precomputed_reports_skip_routing(fixture_pdfs, tmp_path, monkeypatch):
    reports = _route(fixture_pdfs, "clean_book")
    calls = []
    monkeypatch.setattr(
        confidence_router,
        "route_document",
        lambda *a, **k: calls.append(1) or reports,
    )
    result = _convert(fixture_pdfs, tmp_path, precomputed_reports=reports)
    assert calls == []  # internal routing never ran
    assert result["success"] is True


def test_precomputed_reports_drive_the_same_summary(fixture_pdfs, tmp_path):
    reports = _route(fixture_pdfs, "two_column")
    result = _convert(
        fixture_pdfs, tmp_path, pdf="two_column", precomputed_reports=reports
    )
    assert result["routing"]["tier2_digest"] >= 1
    assert result["success"] is True


def test_precomputed_reports_length_mismatch_raises(fixture_pdfs, tmp_path):
    reports = _route(fixture_pdfs, "clean_book")
    with pytest.raises(ValueError):
        _convert(
            fixture_pdfs,
            tmp_path,
            pdf="single_column",
            precomputed_reports=reports,
        )
