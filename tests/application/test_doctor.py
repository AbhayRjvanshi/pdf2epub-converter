"""Phase 13: doctor - mockable probes, no network by default.

No Java/Node required: every system probe is monkeypatched.
"""

from pathlib import Path

from pdf2epub.application import doctor
from pdf2epub.application.doctor import FAIL, OK, OPTIONAL, WARN, run_doctor
from pdf2epub.config import AppConfig
from pdf2epub.engine import packaging_and_validation as pk
from pdf2epub.providers.models import ModelCapabilities, ModelDefinition
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import build_registry
from pdf2epub.validators.base import DetectionOutcome, ValidatorState


class _FakeValidator:
    def __init__(self, validator_id, state, version=""):
        self.id = validator_id
        self.display_name = validator_id
        self._state = state
        self._version = version

    def detect(self):
        return DetectionOutcome(self._state, version=self._version)

    def validate(self, epub_path):
        raise NotImplementedError


class _ValidatorRegistry:
    def __init__(self, *validators):
        self._validators = list(validators)

    def list(self):
        return list(self._validators)


class _FakeConfigManager:
    def __init__(self, config=None, path=None):
        self._config = config or AppConfig()
        self._path = Path(path) if path else Path("no-such-config.toml")

    def load(self):
        return self._config

    def path(self):
        return self._path


def _state_of(report, name):
    return next(c.state for c in report.checks if c.name == name)


def _run(tmp_path, monkeypatch, *, config=None, session=None, verify=False,
         validators=None, environ=None, registry=None):
    monkeypatch.setattr(doctor, "_module_available", lambda name: True)
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)  # no Java/Node
    monkeypatch.setattr(
        doctor, "_probe_version", lambda cmd, timeout=10: (True, "probe")
    )
    return run_doctor(
        registry=registry if registry is not None else build_registry(),
        config_manager=_FakeConfigManager(config, path=tmp_path / "config.toml"),
        environ=environ if environ is not None else {},
        session=session,
        validator_registry=validators,
        verify_credentials=verify,
    )


def test_healthy_environment_reports_no_failures(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch)
    assert not report.failed
    assert _state_of(report, "python") == OK
    assert _state_of(report, "core packages") == OK


def test_missing_core_package_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor, "_module_available", lambda name: name != "pymupdf"
    )
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
    report = run_doctor(
        registry=build_registry(),
        config_manager=_FakeConfigManager(path=tmp_path / "config.toml"),
        environ={},
    )
    assert _state_of(report, "core packages") == FAIL
    assert report.failed


def test_absent_optional_sdks_never_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor,
        "_module_available",
        lambda name: name not in ("openai", "anthropic", "keyring"),
    )
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
    report = run_doctor(
        registry=build_registry(),
        config_manager=_FakeConfigManager(path=tmp_path / "config.toml"),
        environ={},
    )
    assert _state_of(report, "openai SDK") == OPTIONAL
    assert _state_of(report, "anthropic SDK") == OPTIONAL
    assert _state_of(report, "keyring") == OPTIONAL
    assert not report.failed


def test_shared_sdk_groups_openai_and_nvidia_into_one_row(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_module_available", lambda name: name != "openai")
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
    report = run_doctor(
        registry=build_registry(),
        config_manager=_FakeConfigManager(path=tmp_path / "config.toml"),
        environ={},
    )
    row = next(c for c in report.checks if c.name == "openai SDK")
    assert row.state == OPTIONAL
    assert "openai, nvidia" in row.detail
    assert "pdf2epub[nvidia] or pdf2epub[openai]" in row.detail  # sorted extras
    assert not any(c.name == "nvidia SDK" for c in report.checks)


def test_installed_sdk_row_names_its_consumer_providers(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch)
    row = next(c for c in report.checks if c.name == "openai SDK")
    assert row.state == OK
    assert "openai" in row.detail and "nvidia" in row.detail


def test_configured_provider_missing_sdk_warns_separately_from_credentials(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(doctor, "_module_available", lambda name: name != "openai")
    monkeypatch.setattr(pk, "resolve_tool", lambda cmd: None)
    report = run_doctor(
        registry=build_registry(),
        config_manager=_FakeConfigManager(
            AppConfig(provider_name="nvidia"), path=tmp_path / "config.toml"
        ),
        environ={},
    )
    sdk = next(c for c in report.checks if c.name == "provider SDK")
    assert sdk.state == WARN
    assert "nvidia" in sdk.detail and "pdf2epub[nvidia]" in sdk.detail
    credentials = next(c for c in report.checks if c.name == "credentials")
    assert credentials.state == WARN
    assert "NVIDIA_API_KEY" in credentials.detail
    assert not report.failed


def test_absent_java_and_node_are_optional(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch)
    assert _state_of(report, "java") == OPTIONAL
    assert _state_of(report, "node") == OPTIONAL


def test_missing_enabled_validator_is_warn_not_fail(tmp_path, monkeypatch):
    validators = _ValidatorRegistry(
        _FakeValidator("epubcheck", ValidatorState.UNAVAILABLE),
        _FakeValidator("ace", ValidatorState.AVAILABLE, version="1.3.0"),
    )
    report = _run(tmp_path, monkeypatch, validators=validators)
    assert _state_of(report, "epubcheck") == WARN
    assert _state_of(report, "ace") == OK
    assert not report.failed


def test_doctor_is_offline_by_default(tmp_path, monkeypatch):
    registry = build_registry()
    adapter = registry.get("openai")
    calls = []
    monkeypatch.setattr(
        adapter, "validate_credentials", lambda credential: calls.append(credential) or True
    )
    config = AppConfig(provider_name="openai")
    report = _run(
        tmp_path,
        monkeypatch,
        config=config,
        environ={"OPENAI_API_KEY": "sk-env"},
        registry=registry,
    )
    assert _state_of(report, "credentials") == OK
    assert calls == []  # no network without explicit verification
    assert not any(c.name == "credential verification" for c in report.checks)


def test_explicit_verification_reaches_the_provider(tmp_path, monkeypatch):
    registry = build_registry()
    adapter = registry.get("openai")
    calls = []
    monkeypatch.setattr(
        adapter, "validate_credentials", lambda credential: calls.append(credential) or True
    )
    config = AppConfig(provider_name="openai")
    report = _run(
        tmp_path,
        monkeypatch,
        config=config,
        environ={"OPENAI_API_KEY": "sk-env"},
        registry=registry,
        verify=True,
    )
    assert calls == ["sk-env"]
    assert _state_of(report, "credential verification") == OK


def test_rejected_credential_is_a_failure(tmp_path, monkeypatch):
    registry = build_registry()
    adapter = registry.get("openai")
    monkeypatch.setattr(adapter, "validate_credentials", lambda credential: False)
    report = _run(
        tmp_path,
        monkeypatch,
        config=AppConfig(provider_name="openai"),
        environ={"OPENAI_API_KEY": "sk-bad"},
        registry=registry,
        verify=True,
    )
    assert _state_of(report, "credential verification") == FAIL
    assert report.failed


def test_corrupt_config_is_a_warning(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("not [ valid toml", encoding="utf-8")
    report = _run(tmp_path, monkeypatch)
    assert _state_of(report, "config") == WARN
    assert not report.failed


def test_session_model_route_fit_is_checked(tmp_path, monkeypatch):
    from pdf2epub.application.preflight import PreflightResult
    from pdf2epub.application.session import Session

    synth = ProviderProfile(
        provider_id="synth",
        display_name="Synth",
        api_style="openai",
        credential_env_var="SYNTH_API_KEY",
        models=(
            ModelDefinition(
                "synth", "text-only", "Text Only",
                ModelCapabilities(structured_output=True),
            ),
        ),
    )
    registry = build_registry([synth])
    session = Session()
    session.select_provider("synth")
    session.select_model("text-only")
    session.last_routing = PreflightResult(
        total_pages=1,
        routing_summary={"tier1": 0, "tier2_digest": 0, "tier2_vision": 1},
        required_routes=frozenset({"vision"}),
        bypassed_vision=0,
    )
    report = _run(
        tmp_path,
        monkeypatch,
        session=session,
        environ={"SYNTH_API_KEY": "k"},
        registry=registry,
    )
    assert _state_of(report, "model fit") == WARN
    assert not report.failed  # advisory, not a hard failure


def test_render_contains_states(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch)
    rendered = report.render()
    assert "python" in rendered and "OK" in rendered
