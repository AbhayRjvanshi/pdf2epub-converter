"""Phase 4: the Anthropic-style adapter against a recording fake SDK."""

import sys
import types

import pytest

from pdf2epub.providers.anthropic_style import AnthropicStyleAdapter
from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.errors import CredentialError, ProviderUnavailableError

ANTHROPIC_PROFILE = next(p for p in PROFILES if p.provider_id == "anthropic")


class _FakeSDKError(Exception):
    def __init__(self, status_code, message, headers=None):
        super().__init__(message)
        self.status_code = status_code
        if headers is not None:
            self.response = types.SimpleNamespace(headers=headers)


class _RecordingAnthropicClient:
    def __init__(
        self,
        *,
        response_blocks=(),
        create_error=None,
        models_error=None,
        with_models_route=True,
    ):
        self.init_kwargs = None
        self.create_calls = []
        self._response_blocks = list(response_blocks)
        self._create_error = create_error
        self._models_error = models_error
        self.messages = types.SimpleNamespace(create=self._create)
        if with_models_route:
            self.models = types.SimpleNamespace(list=self._list_models)

    def _create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self._create_error is not None:
            raise self._create_error
        return types.SimpleNamespace(content=list(self._response_blocks))

    def _list_models(self):
        if self._models_error is not None:
            raise self._models_error
        return []


def _install_fake_anthropic(monkeypatch, client):
    def factory(**kwargs):
        client.init_kwargs = kwargs
        return client

    module = types.ModuleType("anthropic")
    module.Anthropic = factory
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return client


def _text_block(text):
    return types.SimpleNamespace(type="text", text=text)


def test_text_invocation_shape_matches_engine_parity(monkeypatch):
    client = _install_fake_anthropic(
        monkeypatch,
        _RecordingAnthropicClient(response_blocks=[_text_block("hello")]),
    )
    llm = AnthropicStyleAdapter(ANTHROPIC_PROFILE).create_llm_callable(
        "claude-sonnet-4-5", "sk-ant"
    )

    assert llm("SYSTEM PROMPT", "payload text") == "hello"

    call = client.create_calls[0]
    assert call["model"] == "claude-sonnet-4-5"
    assert call["max_tokens"] == 8192
    assert call["temperature"] == 0.0
    assert call["system"] == "SYSTEM PROMPT"
    assert call["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "payload text"}]}
    ]
    assert client.init_kwargs == {"api_key": "sk-ant"}


def test_image_block_precedes_text_block(monkeypatch):
    client = _install_fake_anthropic(
        monkeypatch,
        _RecordingAnthropicClient(response_blocks=[_text_block("ok")]),
    )
    llm = AnthropicStyleAdapter(ANTHROPIC_PROFILE).create_llm_callable(
        "claude-sonnet-4-5", "k"
    )
    llm("SYS", "describe", image_b64="aGk=")

    blocks = client.create_calls[0]["messages"][0]["content"]
    assert blocks[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "aGk="},
    }
    assert blocks[1] == {"type": "text", "text": "describe"}


def test_response_text_blocks_are_joined_and_empty_falls_back(monkeypatch):
    client = _RecordingAnthropicClient(
        response_blocks=[
            _text_block("a"),
            types.SimpleNamespace(type="tool_use"),
            _text_block("b"),
        ]
    )
    _install_fake_anthropic(monkeypatch, client)
    llm = AnthropicStyleAdapter(ANTHROPIC_PROFILE).create_llm_callable(
        "claude-sonnet-4-5", "k"
    )
    assert llm("SYS", "p") == "ab"

    empty = _RecordingAnthropicClient(response_blocks=[])
    _install_fake_anthropic(monkeypatch, empty)
    llm2 = AnthropicStyleAdapter(ANTHROPIC_PROFILE).create_llm_callable(
        "claude-sonnet-4-5", "k"
    )
    assert llm2("SYS", "p") == "{}"


def test_missing_sdk_raises_unavailable_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        AnthropicStyleAdapter(ANTHROPIC_PROFILE).create_llm_callable(
            "claude-sonnet-4-5", "k"
        )
    assert "pip install" in str(excinfo.value)


def test_validate_uses_models_route_when_present(monkeypatch):
    client = _RecordingAnthropicClient()
    _install_fake_anthropic(monkeypatch, client)
    assert AnthropicStyleAdapter(ANTHROPIC_PROFILE).validate_credentials("k") is True


def test_validate_falls_back_to_one_token_ping_without_models_route(monkeypatch):
    client = _RecordingAnthropicClient(with_models_route=False)
    _install_fake_anthropic(monkeypatch, client)
    assert AnthropicStyleAdapter(ANTHROPIC_PROFILE).validate_credentials("k") is True
    ping = client.create_calls[0]
    assert ping["max_tokens"] == 1
    assert ping["model"] == "claude-sonnet-4-5"


def test_rejected_credentials_return_false(monkeypatch):
    client = _RecordingAnthropicClient(models_error=_FakeSDKError(401, "bad key"))
    _install_fake_anthropic(monkeypatch, client)
    assert AnthropicStyleAdapter(ANTHROPIC_PROFILE).validate_credentials("k") is False
