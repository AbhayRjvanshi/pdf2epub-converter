"""Phase 5: the keyring boundary - one scheme, one error envelope."""

import logging

from pdf2epub.config.credentials import (
    KEYRING_SERVICE,
    keyring_delete,
    keyring_store,
    resolve_credential,
)


def test_store_and_resolution_roundtrip(fake_keyring):
    assert keyring_store("openai", "sk-1") is True
    assert fake_keyring.set_calls == [(KEYRING_SERVICE, "openai", "sk-1")]
    result = resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
    assert (result.credential, result.source) == ("sk-1", "keyring")


def test_store_failure_returns_false_without_raising(fake_keyring):
    fake_keyring.set_error = RuntimeError("locked keychain")
    assert keyring_store("openai", "sk-1") is False


def test_delete_is_idempotent(fake_keyring):
    keyring_store("openai", "sk-1")
    assert keyring_delete("openai") is True
    assert keyring_delete("openai") is True
    assert resolve_credential(
        "openai", env_var="OPENAI_API_KEY", environ={}
    ).credential is None


def test_delete_failure_returns_false_without_raising(fake_keyring):
    fake_keyring.delete_error = RuntimeError("backend refusing")
    assert keyring_delete("openai") is False


def test_backend_read_errors_degrade_to_unavailable(fake_keyring, caplog):
    fake_keyring.get_error = RuntimeError("no dbus")
    with caplog.at_level(logging.DEBUG, logger="pdf2epub.config.credentials"):
        result = resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
    assert result.source == "unavailable"
    assert result.credential is None
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


def test_absent_keyring_package_degrades_everywhere(no_keyring, caplog):
    with caplog.at_level(logging.DEBUG, logger="pdf2epub.config.credentials"):
        result = resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
        stored = keyring_store("openai", "x")
        deleted = keyring_delete("openai")
    assert result.source == "unavailable"
    assert stored is False
    assert deleted is False
    assert any("not installed" in r.getMessage() for r in caplog.records)


def test_stderr_is_never_touched_by_the_boundary(fake_keyring, capsys):
    fake_keyring.get_error = RuntimeError("boom")
    resolve_credential("openai", env_var="OPENAI_API_KEY", environ={})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
