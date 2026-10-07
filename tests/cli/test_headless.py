"""Phase 10: the headless CLI - mapping, exit codes and a few real runs.

Parsing/mapping tests never convert; dispatch tests replace the service;
the E2E section runs the real service over fixtures plus one real
subprocess invocation through ``python -m pdf2epub``.
"""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from pdf2epub.application import ConversionResult, PreflightResult
from pdf2epub.cli import headless
from pdf2epub.config import AppConfig
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import build_registry

CHOICES = ["none", "openai", "anthropic"]


def _parse(argv, choices=CHOICES):
    return headless.build_parser(choices).parse_args(argv)


def _request(argv, *, registry=None, config=None, choices=CHOICES):
    args = _parse(argv, choices)
    return headless.request_from_args(
        args, registry=registry or build_registry(), config=config or AppConfig()
    )


def _subprocess_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent.parent / "src")
    return env


# -- flag -> DTO mapping (pure; no conversion) ------------------------------

def test_defaults_map_to_the_dto(tmp_path):
    request = _request(["convert", str(tmp_path / "b.pdf")])
    assert request.output_path == Path("output.epub")
    assert request.provider_id == "none"
    assert request.conversion_model is None
    assert request.title is None and request.author is None
    options = request.options
    assert options.spool_images is True
    assert options.overwrite is False
    assert options.cache_dir is None  # no CLI override; service layers config
    assert options.max_tier2_pages is None


def test_every_flag_maps_to_its_field(tmp_path):
    request = _request(
        [
            "convert", str(tmp_path / "b.pdf"), "-o", str(tmp_path / "o.epub"),
            "--title", "T", "--author", "A",
            "--provider", "openai", "--model", "gpt-4o-mini",
            "--batch-size", "7", "--cache-dir", str(tmp_path / "c"),
            "--max-repair-attempts", "3", "--skip-validation", "--report-only",
            "--font-sample-pages", "9", "--no-spool-images", "--quiet", "--force",
            "--max-tier2-pages", "5",
        ]
    )
    assert request.pdf_path == tmp_path / "b.pdf"
    assert request.output_path == tmp_path / "o.epub"
    assert request.title == "T" and request.author == "A"
    assert request.provider_id == "openai"
    assert request.conversion_model == "gpt-4o-mini"
    o = request.options
    assert o.batch_size == 7
    assert o.cache_dir == str(tmp_path / "c")
    assert o.max_repair_attempts == 3
    assert o.skip_validation is True
    assert o.report_only is True
    assert o.font_sample_pages == 9
    assert o.spool_images is False  # --no-spool-images inversion
    assert o.quiet is True
    assert o.overwrite is True  # --force
    assert o.max_tier2_pages == 5


def test_omitted_model_auto_selects_the_first_catalog_model(tmp_path):
    request = _request(["convert", str(tmp_path / "b.pdf"), "--provider", "anthropic"])
    assert request.conversion_model == "claude-sonnet-4-5"


def test_empty_catalog_provider_yields_a_clean_config_error(tmp_path):
    empty = ProviderProfile(
        provider_id="empty",
        display_name="Empty",
        api_style="openai",
        credential_env_var="EMPTY_API_KEY",
        models=(),
    )
    registry = build_registry([empty])
    request = _request(
        ["convert", str(tmp_path / "b.pdf"), "--provider", "empty"],
        registry=registry,
        choices=["none", "empty"],
    )
    assert request.conversion_model is None  # no IndexError

    from pdf2epub.application import validate_request

    assessment = validate_request(
        request, registry=registry, environ={"EMPTY_API_KEY": "k"}
    )
    assert any("requires a conversion_model" in e for e in assessment.config_errors)


def test_cli_omission_falls_back_to_config(tmp_path):
    config = AppConfig(provider_name="anthropic", conversion_model="claude-sonnet-4-5")
    request = _request(["convert", str(tmp_path / "b.pdf")], config=config)
    assert request.provider_id == "anthropic"
    assert request.conversion_model == "claude-sonnet-4-5"


def test_cli_flag_beats_config(tmp_path):
    config = AppConfig(provider_name="anthropic")
    request = _request(
        ["convert", str(tmp_path / "b.pdf"), "--provider", "openai", "--model", "gpt-4o"],
        config=config,
    )
    assert request.provider_id == "openai"
    assert request.conversion_model == "gpt-4o"


# -- dispatch and exit codes (fake service) ---------------------------------

class _FakeConfigManager:
    config = AppConfig()

    def load(self):
        return _FakeConfigManager.config


class _FakeService:
    last_request = None
    last_config = None
    result = ConversionResult(success=True)
    interrupt = False

    def __init__(self, *, registry=None, config=None, **kwargs):
        _FakeService.last_config = config

    def convert(self, request, *, explicit_secret=None):
        _FakeService.last_request = request
        if _FakeService.interrupt:
            raise KeyboardInterrupt
        return _FakeService.result


@pytest.fixture
def fake_cli(monkeypatch):
    monkeypatch.setattr(headless, "ConversionService", _FakeService)
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    _FakeService.last_request = None
    _FakeService.result = ConversionResult(success=True)
    _FakeService.interrupt = False
    return _FakeService


def test_success_returns_zero(fake_cli, tmp_path):
    assert headless.main(["convert", str(tmp_path / "b.pdf")]) == 0


def test_input_error_returns_two(fake_cli, tmp_path):
    _FakeService.result = ConversionResult(success=False, input_errors=["nope"])
    assert headless.main(["convert", str(tmp_path / "b.pdf")]) == 2


def test_config_error_returns_one(fake_cli, tmp_path):
    _FakeService.result = ConversionResult(success=False, config_errors=["bad"])
    assert headless.main(["convert", str(tmp_path / "b.pdf")]) == 1


def test_cancelled_result_returns_130(fake_cli, tmp_path):
    _FakeService.result = ConversionResult(success=False, cancelled=True)
    assert headless.main(["convert", str(tmp_path / "b.pdf")]) == 130


def test_keyboard_interrupt_is_a_cli_guard_returning_130(fake_cli, tmp_path, capsys):
    _FakeService.interrupt = True
    assert headless.main(["convert", str(tmp_path / "b.pdf")]) == 130
    assert "cancelled" in capsys.readouterr().err


def test_warnings_and_errors_go_to_stderr(fake_cli, tmp_path, capsys):
    _FakeService.result = ConversionResult(
        success=False, warnings=["w1"], config_errors=["e1"]
    )
    headless.main(["convert", str(tmp_path / "b.pdf")])
    captured = capsys.readouterr()
    assert "[WARNING] w1" in captured.err
    assert "[ERROR] e1" in captured.err
    assert captured.out == ""


def test_quiet_suppresses_warnings_but_not_errors(fake_cli, tmp_path, capsys):
    _FakeService.result = ConversionResult(
        success=False, warnings=["w1"], config_errors=["e1"]
    )
    headless.main(["convert", str(tmp_path / "b.pdf"), "--quiet"])
    captured = capsys.readouterr()
    assert "w1" not in captured.err
    assert "[ERROR] e1" in captured.err


def test_report_only_prints_the_routing_table(fake_cli, tmp_path, capsys):
    pre = PreflightResult(
        total_pages=1,
        routing_summary={"tier1": 1, "tier2_digest": 0, "tier2_vision": 0},
        required_routes=frozenset(),
        bypassed_vision=0,
        cost_advisory="~0 Tier-2 page(s) (0 digest, 0 vision)",
        reports=(),
    )
    _FakeService.result = ConversionResult(
        success=True, report_only=True, preflight=pre
    )
    assert headless.main(["convert", str(tmp_path / "b.pdf"), "--report-only"]) == 0
    out = capsys.readouterr().out
    assert "page" in out and "score" in out
    assert "Tier-2" in out


def test_report_only_without_preflight_does_not_crash(fake_cli, tmp_path):
    _FakeService.result = ConversionResult(
        success=True, report_only=True, preflight=None
    )
    assert headless.main(["convert", str(tmp_path / "b.pdf"), "--report-only"]) == 0


def test_version_returns_zero(capsys):
    assert headless.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("pdf2epub ")


def test_no_subcommand_returns_two(monkeypatch):
    monkeypatch.setattr(headless, "_stdin_is_tty", lambda: False)
    assert headless.main([]) == 2


def test_unknown_provider_is_a_usage_error(tmp_path):
    assert headless.main(["convert", str(tmp_path / "b.pdf"), "--provider", "nope"]) == 2


def test_service_receives_the_loaded_config(fake_cli, tmp_path):
    headless.main(["convert", str(tmp_path / "b.pdf")])
    assert _FakeService.last_config is not None


# -- real end-to-end runs ----------------------------------------------------

def test_real_offline_conversion_end_to_end(fixture_pdfs, tmp_path):
    out = tmp_path / "cli.epub"
    code = headless.main(
        [
            "convert", fixture_pdfs["single_column"], "-o", str(out),
            "--provider", "none", "--quiet", "--skip-validation",
            "--cache-dir", str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        assert "mimetype" in zf.namelist()


def test_real_report_only_writes_nothing(fixture_pdfs, tmp_path, capsys):
    out = tmp_path / "never.epub"
    code = headless.main(
        [
            "convert", fixture_pdfs["two_column"], "-o", str(out),
            "--provider", "none", "--report-only",
            "--cache-dir", str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    assert not out.exists()
    assert "page" in capsys.readouterr().out


def test_output_directory_is_created(fixture_pdfs, tmp_path):
    out = tmp_path / "nested" / "deep" / "cli.epub"
    code = headless.main(
        [
            "convert", fixture_pdfs["single_column"], "-o", str(out),
            "--provider", "none", "--quiet", "--skip-validation",
            "--cache-dir", str(tmp_path / "cache"),
        ]
    )
    assert code == 0 and out.exists()


def test_subprocess_conversion_through_python_m(fixture_pdfs, tmp_path):
    out = tmp_path / "sub.epub"
    proc = subprocess.run(
        [
            sys.executable, "-m", "pdf2epub", "convert",
            fixture_pdfs["single_column"], "-o", str(out),
            "--provider", "none", "--skip-validation", "--quiet",
            "--cache-dir", str(tmp_path / "cache"),
        ],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


# -- doctor and validators subcommands ---------------------------------------

def _doctor_report(*checks):
    from pdf2epub.application import DoctorReport
    from pdf2epub.application.doctor import CheckResult

    return DoctorReport(checks=[CheckResult(*check) for check in checks])


def test_doctor_exits_zero_when_nothing_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        headless, "run_doctor", lambda **kwargs: _doctor_report(("python", "OK", "3.10.6"))
    )
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    assert headless.main(["doctor"]) == 0
    assert "python" in capsys.readouterr().out


def test_doctor_exits_one_when_a_check_fails(monkeypatch):
    monkeypatch.setattr(
        headless,
        "run_doctor",
        lambda **kwargs: _doctor_report(("core packages", "FAIL", "missing: pymupdf")),
    )
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    assert headless.main(["doctor"]) == 1


def test_doctor_verify_flag_is_mapped(monkeypatch):
    captured = {}

    def fake_doctor(**kwargs):
        captured.update(kwargs)
        return _doctor_report()

    monkeypatch.setattr(headless, "run_doctor", fake_doctor)
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    assert headless.main(["doctor", "--verify-credentials"]) == 0
    assert captured["verify_credentials"] is True


def test_validators_lists_states(monkeypatch, capsys):
    from pdf2epub.validators.base import DetectionOutcome, ValidatorState

    class _V:
        def __init__(self, validator_id, state):
            self.id = validator_id
            self.display_name = validator_id
            self._state = state

        def detect(self):
            return DetectionOutcome(self._state)

    class _VR:
        def list(self):
            return [
                _V("epubcheck", ValidatorState.UNAVAILABLE),
                _V("ace", ValidatorState.AVAILABLE),
            ]

    monkeypatch.setattr(headless, "build_validator_registry", lambda: _VR())
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    assert headless.main(["validators"]) == 0
    out = capsys.readouterr().out
    assert "epubcheck" in out and "required_but_missing" in out
    assert "available" in out


# -- interactive entry points ------------------------------------------------

class _FakeRepl:
    kwargs = None

    def __init__(self, **kwargs):
        _FakeRepl.kwargs = kwargs

    def run(self):
        return 0


def test_bare_invocation_launches_the_repl_with_a_tty(monkeypatch):
    monkeypatch.setattr(headless, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(headless, "Repl", _FakeRepl)
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    _FakeRepl.kwargs = None
    assert headless.main([]) == 0
    assert _FakeRepl.kwargs is not None
    assert _FakeRepl.kwargs["onboarding"] is True


def test_bare_invocation_without_a_tty_prints_guidance(monkeypatch, capsys):
    monkeypatch.setattr(headless, "_stdin_is_tty", lambda: False)
    assert headless.main([]) == 2
    assert "terminal" in capsys.readouterr().err


def test_interactive_subcommand_runs_without_a_tty(monkeypatch):
    monkeypatch.setattr(headless, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(headless, "Repl", _FakeRepl)
    monkeypatch.setattr(headless, "ConfigManager", _FakeConfigManager)
    _FakeRepl.kwargs = None
    assert headless.main(["interactive"]) == 0
    assert _FakeRepl.kwargs["onboarding"] is False  # piped sessions never onboard


def test_interactive_subprocess_piped_session():
    proc = subprocess.run(
        [sys.executable, "-m", "pdf2epub", "interactive"],
        input="/help\n/exit\n",
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Available commands" in proc.stdout
