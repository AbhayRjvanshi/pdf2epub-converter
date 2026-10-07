"""Phase 13: wrappers delegate to their one engine method; detection shares
the engine's single resolver, so detection and execution cannot disagree."""

import subprocess

from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.validators.ace import AceValidator
from pdf2epub.validators.base import ValidationResult, ValidatorState
from pdf2epub.validators.epubcheck import EpubcheckValidator


def _completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def test_detect_without_resolution_is_unavailable(monkeypatch):
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
    assert EpubcheckValidator().detect().state is ValidatorState.UNAVAILABLE
    assert AceValidator().detect().state is ValidatorState.UNAVAILABLE


def test_detect_captures_the_version(monkeypatch):
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/fake/epubcheck")
    monkeypatch.setattr(
        pk,
        "_run_with_tree_kill",
        lambda cmd, timeout: _completed(cmd, 0, "EPUBCheck 5.1.0\n"),
    )
    outcome = EpubcheckValidator().detect()
    assert outcome.state is ValidatorState.AVAILABLE
    assert outcome.version == "EPUBCheck 5.1.0"


def test_probe_timeout_is_failed_to_run_not_unavailable(monkeypatch):
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/fake/epubcheck")

    def boom(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(pk, "_run_with_tree_kill", boom)
    assert EpubcheckValidator().detect().state is ValidatorState.FAILED_TO_RUN


def test_probe_nonzero_exit_is_failed_to_run(monkeypatch):
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: "C:/fake/ace")
    monkeypatch.setattr(
        pk,
        "_run_with_tree_kill",
        lambda cmd, timeout: _completed(cmd, 1, "", "boom"),
    )
    outcome = AceValidator().detect()
    assert outcome.state is ValidatorState.FAILED_TO_RUN
    assert "boom" in outcome.detail


def test_epubcheck_wrapper_never_invokes_ace(monkeypatch):
    calls = []
    wrapper = EpubcheckValidator()
    monkeypatch.setattr(
        wrapper._validator,
        "run_epubcheck",
        lambda path, work_dir=None: calls.append("epubcheck") or (True, 0, "ok", True),
    )
    monkeypatch.setattr(
        wrapper._validator,
        "run_daisy_ace",
        lambda *a, **k: calls.append("ace") or (True, {}, "", False),
    )
    result = wrapper.validate("book.epub")
    assert calls == ["epubcheck"]  # the other engine method is never touched
    assert isinstance(result, ValidationResult) and result.passed


def test_ace_wrapper_never_invokes_epubcheck(monkeypatch):
    calls = []
    wrapper = AceValidator()
    monkeypatch.setattr(
        wrapper._validator,
        "run_daisy_ace",
        lambda path, out_dir=None: calls.append("ace") or (True, {}, "ok", True),
    )
    monkeypatch.setattr(
        wrapper._validator,
        "run_epubcheck",
        lambda *a, **k: calls.append("epubcheck") or (True, 0, "", False),
    )
    result = wrapper.validate("book.epub")
    assert calls == ["ace"]
    assert result.passed


def test_wrapper_reports_unavailable_validation_honestly(monkeypatch):
    wrapper = EpubcheckValidator()
    monkeypatch.setattr(
        wrapper._validator,
        "run_epubcheck",
        lambda path, work_dir=None: (True, 0, "not installed", False),
    )
    result = wrapper.validate("book.epub")
    assert result.available is False
    assert "not installed" in result.detail
