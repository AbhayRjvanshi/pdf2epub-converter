"""Phase 5: the resolution chain - precedence, honesty, hygiene."""

import logging
import types

import pytest

from pdf2epub.config.credentials import (
    GENERIC_ENV_VAR,
    KEYRING_SERVICE,
    resolve_credential,
    resolve_for_profile,
)


def test_explicit_secret_beats_everything(fake_keyring):
    fake_keyring.store["openai"] = "from-keyring"
    result = resolve_credential(
        "openai",
        env_var="OPENAI_API_KEY",
        explicit_secret="  from-explicit  ",
        environ={"OPENAI_API_KEY": "from-env"},
    )
    assert result.credential == "from-explicit"
    assert result.source == "explicit"
    assert result.warning is None


def test_environment_beats_keyring(fake_keyring):
    fake_keyring.store["openai"] = "from-keyring"
    result = resolve_credential(
        "openai", env_var="OPENAI_API_KEY", environ={"OPENAI_API_KEY": "from-env"}
    )
    assert (result.credential, result.source) == ("from-env", "environment")


def test_keyring_used_when_env_absent(fake_keyring):
    fake_keyring.store["openai"] = "from-keyring"
    result = resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
    assert (result.credential, result.source) == ("from-keyring", "keyring")
    assert fake_keyring.get_calls == [(KEYRING_SERVICE, "openai")]


def test_unavailable_when_nothing_has_a_secret(fake_keyring):
    result = resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
    assert result.credential is None
    assert result.source == "unavailable"
    assert result.warning is None


def test_provider_env_var_beats_generic():
    env = {"OPENAI_API_KEY": "specific", GENERIC_ENV_VAR: "generic"}
    result = resolve_credential(
        "openai", env_var="OPENAI_API_KEY", allow_generic_key=True, environ=env
    )
    assert result.source == "environment"
    assert result.credential == "specific"


def test_generic_key_requires_opt_in():
    result = resolve_credential(
        "openai", env_var="OPENAI_API_KEY", environ={GENERIC_ENV_VAR: "generic"}
    )
    assert result.source == "unavailable"


def test_generic_key_accepted_with_warning_when_opted_in():
    result = resolve_credential(
        "openrouter",
        env_var="OPENROUTER_API_KEY",
        allow_generic_key=True,
        environ={GENERIC_ENV_VAR: "generic"},
    )
    assert result.source == "generic_environment"
    assert result.credential == "generic"
    assert GENERIC_ENV_VAR in (result.warning or "")
    assert "openrouter" in (result.warning or "")


def test_generic_var_identical_to_provider_var_is_not_double_checked():
    result = resolve_credential(
        "x", env_var=GENERIC_ENV_VAR, allow_generic_key=True,
        environ={GENERIC_ENV_VAR: "k"},
    )
    assert result.source == "environment"


def test_whitespace_environment_values_are_treated_as_absent(fake_keyring):
    fake_keyring.store["openai"] = "from-keyring"
    result = resolve_credential(
        "openai", env_var="OPENAI_API_KEY", environ={"OPENAI_API_KEY": "   "}
    )
    assert result.source == "keyring"


def test_empty_explicit_secret_is_skipped_with_warning(fake_keyring):
    result = resolve_credential(
        "openai", env_var="OPENAI_API_KEY", explicit_secret="   ", environ={}
    )
    assert result.source == "unavailable"
    assert result.warning is not None
    assert "ignored" in result.warning


def test_empty_explicit_secret_does_not_block_the_rest_of_the_chain(fake_keyring):
    result = resolve_credential(
        "openai",
        env_var="OPENAI_API_KEY",
        explicit_secret="",
        environ={"OPENAI_API_KEY": "from-env"},
    )
    assert result.source == "environment"


def test_offline_provider_needs_no_credential():
    result = resolve_credential("none", env_var="")
    assert result.source == "unavailable"
    assert "needs no credential" in (result.warning or "")


def test_contract_misuse_raises_value_error():
    with pytest.raises(ValueError):
        resolve_credential("", env_var="X")
    with pytest.raises(ValueError):
        resolve_credential("openai", env_var="")


def test_resolve_for_profile_duck_types_without_importing_providers(fake_keyring):
    profile = types.SimpleNamespace(
        provider_id="probe",
        credential_env_var="PROBE_API_KEY",
        allow_generic_key=False,
    )
    result = resolve_for_profile(profile, environ={"PROBE_API_KEY": "probe-key"})
    assert (result.credential, result.source) == ("probe-key", "environment")

    # the offline provider has no credential facts at all and still
    # resolves to its clean "needs no credential" result
    from pdf2epub.providers.offline import OfflineProvider

    offline = resolve_for_profile(OfflineProvider())
    assert offline.source == "unavailable"
    assert "needs no credential" in (offline.warning or "")


def test_secret_never_reaches_logs_or_warnings(fake_keyring, caplog):
    secret = "sk-live-never-log-me"
    fake_keyring.get_error = RuntimeError(f"backend exploded near {secret}")
    with caplog.at_level(logging.DEBUG, logger="pdf2epub.config.credentials"):
        result = resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
    assert result.source == "unavailable"
    for record in caplog.records:
        assert secret not in record.getMessage()
    assert secret not in (result.warning or "")


def test_default_environ_is_os_environ(monkeypatch, fake_keyring):
    monkeypatch.setenv("OPENAI_API_KEY", "from-real-env")
    result = resolve_credential("openai", env_var="OPENAI_API_KEY")
    assert (result.credential, result.source) == ("from-real-env", "environment")
