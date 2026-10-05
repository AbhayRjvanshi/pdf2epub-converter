"""Phase 4: the OpenAI-style adapter against a recording fake SDK.

Every assertion here is an engine-parity pin: the request shapes must stay
byte-identical to what ``engine/driver.py``'s adapter built inline, so the
Phase 11 extraction cannot drift.
"""

import json
import logging
import sys
import types

import pytest

from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.errors import (
    CredentialError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from pdf2epub.providers.openai_style import OpenAIStyleAdapter
from pdf2epub.providers.profile import CompatOptions, ProviderProfile

OPENAI_PROFILE = next(p for p in PROFILES if p.provider_id == "openai")


class _FakeSDKError(Exception):
    def __init__(self, status_code, message, headers=None):
        super().__init__(message)
        self.status_code = status_code
        if headers is not None:
            self.response = types.SimpleNamespace(headers=headers)


class _RecordingClient:
    def __init__(self, *, response_content="{}", create_error=None, models_error=None):
        self.init_kwargs = None
        self.create_calls = []
        self.models_calls = 0
        self._response_content = response_content
        self._create_error = create_error
        self._models_error = models_error
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )
        self.models = types.SimpleNamespace(list=self._list_models)

    def _create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self._create_error is not None:
            raise self._create_error
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=self._response_content)
                )
            ]
        )

    def _list_models(self):
        self.models_calls += 1
        if self._models_error is not None:
            raise self._models_error
        return []


def _install_fake_openai(monkeypatch, client):
    def factory(**kwargs):
        client.init_kwargs = kwargs
        return client

    module = types.ModuleType("openai")
    module.OpenAI = factory
    monkeypatch.setitem(sys.modules, "openai", module)
    return client


def _digest_payload():
    return json.dumps(
        {
            "instruction": "Convert each page layout digest into semantic XHTML.",
            "page_count": 1,
            "pages": [{"page_num": 1, "layout_digest": []}],
        }
    )


def _probe_profile(**compat):
    return ProviderProfile(
        provider_id="probe",
        display_name="Probe",
        api_style="openai",
        credential_env_var="PROBE_API_KEY",
        base_url="https://probe.test/v1",
        compat=CompatOptions(**compat),
        user_facing=False,
    )


def test_text_invocation_shape_matches_engine_parity(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient())
    adapter = OpenAIStyleAdapter(OPENAI_PROFILE)
    llm = adapter.create_llm_callable("gpt-4o", "sk-test-key")

    assert llm("SYSTEM PROMPT", _digest_payload()) == "{}"

    call = client.create_calls[0]
    assert call["model"] == "gpt-4o"
    assert call["temperature"] == 0.0
    assert call["response_format"] == {"type": "json_object"}
    assert call["messages"] == [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {"role": "user", "content": _digest_payload()},
    ]
    assert client.init_kwargs == {"api_key": "sk-test-key"}


def test_image_invocation_carries_data_url(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient())
    llm = OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable("gpt-4o", "k")
    llm("SYS", "describe", image_b64="aGk=")
    content = client.create_calls[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64,aGk="


def test_empty_response_content_becomes_empty_json_object(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient(response_content=None))
    llm = OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable("gpt-4o", "k")
    assert llm("SYS", _digest_payload()) == "{}"


def test_json_mode_headers_and_prefix_come_from_compat(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient())
    profile = _probe_profile(
        extra_headers={"X-Probe": "1"},
        supports_json_mode=False,
        model_id_prefix="probe/",
    )
    llm = OpenAIStyleAdapter(profile).create_llm_callable("gpt-4o", "k")
    llm("SYS", _digest_payload())

    assert "response_format" not in client.create_calls[0]
    assert client.create_calls[0]["model"] == "probe/gpt-4o"
    assert client.init_kwargs["base_url"] == "https://probe.test/v1"
    assert client.init_kwargs["default_headers"] == {"X-Probe": "1"}


def test_unknown_model_proceeds_with_warning(monkeypatch, caplog):
    _install_fake_openai(monkeypatch, _RecordingClient())
    with caplog.at_level(logging.WARNING, logger="pdf2epub.providers.openai_style"):
        llm = OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable(
            "totally-new-model", "k"
        )
    assert "not in the static catalog" in caplog.text
    assert callable(llm)


def test_missing_sdk_raises_unavailable_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable("gpt-4o", "k")
    assert "pip install" in str(excinfo.value)


def test_throttling_is_retryable_and_carries_retry_after(monkeypatch):
    err = _FakeSDKError(429, "slow down", headers={"retry-after": "7"})
    _install_fake_openai(monkeypatch, _RecordingClient(create_error=err))
    llm = OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable("gpt-4o", "k")
    with pytest.raises(ProviderRequestError) as excinfo:
        llm("SYS", _digest_payload())
    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after == 7.0


def test_credential_never_survives_an_error(monkeypatch):
    key = "sk-live-supersecret"
    err = _FakeSDKError(401, f"GET https://api.test/v1?key={key} rejected")
    _install_fake_openai(monkeypatch, _RecordingClient(create_error=err))
    llm = OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable("gpt-4o", key)
    with pytest.raises(CredentialError) as excinfo:
        llm("SYS", _digest_payload())
    assert key not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_statusless_errors_degrade_to_unavailable(monkeypatch):
    err = ValueError("weird transport failure")
    _install_fake_openai(monkeypatch, _RecordingClient(create_error=err))
    llm = OpenAIStyleAdapter(OPENAI_PROFILE).create_llm_callable("gpt-4o", "k")
    with pytest.raises(ProviderUnavailableError) as excinfo:
        llm("SYS", _digest_payload())
    assert "ValueError" in str(excinfo.value)


def test_validate_credentials_true_false_and_unavailable(monkeypatch):
    ok = _install_fake_openai(monkeypatch, _RecordingClient())
    assert OpenAIStyleAdapter(OPENAI_PROFILE).validate_credentials("k") is True
    assert ok.models_calls == 1

    rejected = _RecordingClient(models_error=_FakeSDKError(401, "bad key"))
    _install_fake_openai(monkeypatch, rejected)
    assert OpenAIStyleAdapter(OPENAI_PROFILE).validate_credentials("k") is False

    down = _RecordingClient(models_error=_FakeSDKError(503, "down"))
    _install_fake_openai(monkeypatch, down)
    with pytest.raises(ProviderUnavailableError):
        OpenAIStyleAdapter(OPENAI_PROFILE).validate_credentials("k")


def test_models_route_404_still_means_credentials_accepted(monkeypatch):
    # aggregator endpoints without a /models route: auth passed first
    missing = _RecordingClient(models_error=_FakeSDKError(404, "no models route"))
    _install_fake_openai(monkeypatch, missing)
    assert OpenAIStyleAdapter(OPENAI_PROFILE).validate_credentials("k") is True
