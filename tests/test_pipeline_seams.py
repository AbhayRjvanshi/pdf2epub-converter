"""Phase 8: additive engine seams, all defaulted off.

S1 validator selection (this commit); S2 events, S3 cancellation and S5
precomputed routing land in the same file in the following commit.
"""

from pdf2epub.engine import packaging_and_validation as pk


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
