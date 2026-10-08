"""The NVIDIA-style adapter against a recording fake SDK.

No network: the ``openai`` module is replaced with a recording fake, the
integration path NVIDIA documents for its OpenAI-compatible endpoints.
Assertions pin engine parity (request shape, bare callable, error
normalization), the vision-eligible catalog entry, and registry
recognition of the dedicated adapter.
"""

import json
import logging
import sys
import types

import pytest

from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.nvidia_style import NvidiaStyleAdapter
from pdf2epub.providers.profile import ProviderProfile
from pdf2epub.providers.registry import build_registry
from pdf2epub.providers.requirements import (
    check_model_for_routes,
    resolve_model,
    supports_digest,
    supports_vision,
)
from pdf2epub.providers.errors import (
    CredentialError,
    ProviderRequestError,
    ProviderUnavailableError,
)

NVIDIA_PROFILE = next(p for p in PROFILES if p.provider_id == "nvidia")

_WIRE_MODEL = "test-org/test-model"
_BASE_URL = "https://integrate.api.nvidia.com/v1"


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


def test_text_invocation_shape_matches_engine_parity(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient())
    adapter = NvidiaStyleAdapter(NVIDIA_PROFILE)
    model_id = NVIDIA_PROFILE.models[0].model_id  # the provider's default
    llm = adapter.create_llm_callable(model_id, "nvapi-test-key")

    assert llm("SYSTEM PROMPT", _digest_payload()) == "{}"

    call = client.create_calls[0]
    assert call["model"] == model_id
    assert call["temperature"] == 0.0
    assert "response_format" not in call  # supports_json_mode=False in the profile
    assert call["messages"] == [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {"role": "user", "content": _digest_payload()},
    ]
    assert client.init_kwargs["api_key"] == "nvapi-test-key"
    assert client.init_kwargs["base_url"] == _BASE_URL


def test_image_invocation_carries_data_url(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient())
    llm = NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(_WIRE_MODEL, "k")
    llm("SYS", "describe", image_b64="aGk=")
    content = client.create_calls[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64,aGk="


def test_empty_response_content_becomes_empty_json_object(monkeypatch):
    client = _install_fake_openai(monkeypatch, _RecordingClient(response_content=None))
    llm = NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(_WIRE_MODEL, "k")
    assert llm("SYS", _digest_payload()) == "{}"


def test_catalog_registers_both_models_vision_eligible():
    models = NvidiaStyleAdapter(NVIDIA_PROFILE).resolve_models()
    assert [m.model_id for m in models] == [
        "moonshotai/kimi-k3",
        "deepseek-ai/deepseek-v4.1-flash",
    ]
    for model in models:
        assert model.provider_id == "nvidia"
        assert model.status == "active"
        # the appropriate Tier-2 routes: digest and vision, both covered
        assert supports_digest(model) and supports_vision(model)
        assert check_model_for_routes(model, {"digest", "vision"}) == []


def test_resolve_model_finds_both_catalog_entries_without_warning():
    adapter = build_registry().get("nvidia")
    for model in adapter.resolve_models():
        resolution = resolve_model(adapter, model.model_id)
        assert resolution.definition is not None
        assert resolution.definition.model_id == model.model_id
        assert resolution.warning is None


def test_unknown_model_id_warns_but_proceeds(monkeypatch, caplog):
    _install_fake_openai(monkeypatch, _RecordingClient())
    with caplog.at_level(logging.WARNING, logger="pdf2epub.providers.nvidia_style"):
        llm = NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(
            "brand-new/id", "k"
        )
    assert "not in the static catalog" in caplog.text
    assert callable(llm)


def test_missing_sdk_raises_unavailable_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(_WIRE_MODEL, "k")
    assert "pip install" in str(excinfo.value)
    assert "nvidia" in str(excinfo.value)


def test_throttling_is_retryable_and_carries_retry_after(monkeypatch):
    err = _FakeSDKError(429, "slow down", headers={"retry-after": "7"})
    _install_fake_openai(monkeypatch, _RecordingClient(create_error=err))
    llm = NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(_WIRE_MODEL, "k")
    with pytest.raises(ProviderRequestError) as excinfo:
        llm("SYS", _digest_payload())
    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after == 7.0


def test_credential_never_survives_an_error(monkeypatch):
    key = "nvapi-live-supersecret"
    err = _FakeSDKError(401, f"GET {_BASE_URL}?key={key} rejected")
    _install_fake_openai(monkeypatch, _RecordingClient(create_error=err))
    llm = NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(_WIRE_MODEL, key)
    with pytest.raises(CredentialError) as excinfo:
        llm("SYS", _digest_payload())
    assert key not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_timeout_degrades_to_retryable_unavailable(monkeypatch):
    # SDK timeouts carry no status_code; normalize_error's conservative
    # default classifies them as transient (errors.py v2.4 delta).
    err = ValueError("request timed out")
    _install_fake_openai(monkeypatch, _RecordingClient(create_error=err))
    llm = NvidiaStyleAdapter(NVIDIA_PROFILE).create_llm_callable(_WIRE_MODEL, "k")
    with pytest.raises(ProviderUnavailableError) as excinfo:
        llm("SYS", _digest_payload())
    assert "timed out" in str(excinfo.value)
    assert excinfo.value.retryable is True


def test_validate_credentials_true_false_and_unavailable(monkeypatch):
    ok = _install_fake_openai(monkeypatch, _RecordingClient())
    assert NvidiaStyleAdapter(NVIDIA_PROFILE).validate_credentials("k") is True
    assert ok.models_calls == 1

    rejected = _RecordingClient(models_error=_FakeSDKError(401, "bad key"))
    _install_fake_openai(monkeypatch, rejected)
    assert NvidiaStyleAdapter(NVIDIA_PROFILE).validate_credentials("k") is False

    down = _RecordingClient(models_error=_FakeSDKError(503, "down"))
    _install_fake_openai(monkeypatch, down)
    with pytest.raises(ProviderUnavailableError):
        NvidiaStyleAdapter(NVIDIA_PROFILE).validate_credentials("k")


def test_models_route_404_still_means_credentials_accepted(monkeypatch):
    # endpoints without a /models route: auth passed first
    missing = _RecordingClient(models_error=_FakeSDKError(404, "no models route"))
    _install_fake_openai(monkeypatch, missing)
    assert NvidiaStyleAdapter(NVIDIA_PROFILE).validate_credentials("k") is True


def test_profile_pins_endpoint_and_visibility():
    assert NVIDIA_PROFILE.api_style == "nvidia"
    assert NVIDIA_PROFILE.credential_env_var == "NVIDIA_API_KEY"
    assert NVIDIA_PROFILE.base_url == _BASE_URL
    assert len(NVIDIA_PROFILE.models) == 2
    assert NVIDIA_PROFILE.user_facing is True
    assert NVIDIA_PROFILE.compat.supports_json_mode is False


def test_registry_lists_nvidia_as_a_user_facing_provider():
    registry = build_registry()
    adapter = registry.get("nvidia")
    assert isinstance(adapter, NvidiaStyleAdapter)
    assert adapter.provider_id == "nvidia"
    assert adapter.user_facing is True
    assert "nvidia" in {a.provider_id for a in registry.list()}
    assert "nvidia" in {
        a.provider_id for a in registry.list(user_facing_only=False)
    }


def test_nvidia_callable_drives_the_real_engine(tmp_path, monkeypatch):
    """Production path: build_registry -> adapter -> bare LLMClient -> engine.

    Only the callable crosses into the engine; no adapter object, profile
    or SDK type does.
    """
    from pdf2epub.engine.tier2_llm_handler import Tier2Handler, Tier2Request

    class _Client:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(
                            content=json.dumps(
                                {"xhtml_pages": ["<p>engine driven</p>"]}
                            )
                        )
                    )
                ]
            )

    module = types.ModuleType("openai")
    module.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", module)

    adapter = build_registry().get("nvidia")
    client = adapter.create_llm_callable(_WIRE_MODEL, "nvapi-test")
    assert callable(client)
    assert not isinstance(client, type(adapter))

    digest = [
        {
            "line_id": 1,
            "block_id": 1,
            "bbox": [54.0, 90.0, 260.0, 102.0],
            "size": 10.0,
            "bold": False,
            "italic": False,
            "text": "line on page 9",
        }
    ]
    handler = Tier2Handler(llm_client_fn=client, cache_dir=tmp_path)
    pages = handler.process_batch([Tier2Request(page_num=9, layout_digest=digest)])
    assert len(pages) == 1
    assert "engine driven" in pages[0]


def test_compatible_profile_wiring_through_compat_options(monkeypatch):
    # a hypothetical future NVIDIA deployment: custom base URL, headers,
    # model prefix; the adapter is profile-driven like its siblings.
    client = _install_fake_openai(monkeypatch, _RecordingClient())
    from pdf2epub.providers.profile import CompatOptions

    profile = ProviderProfile(
        provider_id="nvidia",
        display_name="NVIDIA",
        api_style="nvidia",
        credential_env_var="NVIDIA_API_KEY",
        base_url="http://localhost:8000/v1",
        compat=CompatOptions(
            extra_headers={"X-Probe": "1"},
            supports_json_mode=True,
            model_id_prefix="org/",
        ),
        models=(),
        user_facing=False,
    )
    llm = NvidiaStyleAdapter(profile).create_llm_callable("model-x", "k")
    llm("SYS", _digest_payload())

    assert client.init_kwargs["base_url"] == "http://localhost:8000/v1"
    assert client.init_kwargs["default_headers"] == {"X-Probe": "1"}
    assert client.create_calls[0]["model"] == "org/model-x"
    assert client.create_calls[0]["response_format"] == {"type": "json_object"}
