"""Phase 11: the legacy permissive bridge (providers.compat).

The bridge exists only for the legacy CLI's documented fallback contract:
unknown provider / missing key / missing SDK -> None. It delegates to the
same Phase 4 adapters the application layer uses, so it carries no wire
code of its own. The engine SDK-free pins are appended in the follow-up
commit that switches the engine onto this bridge.
"""

import os
import sys
import types

import pytest

import pdf2epub.providers.compat as compat
from pdf2epub.providers.compat import create_legacy_llm_client
from pdf2epub.providers.errors import ProviderUnavailableError


class _Profile:
    credential_env_var = "OPENAI_API_KEY"


def _registry_returning(adapter):
    class _Registry:
        def get(self, provider_id):
            return adapter

    return _Registry()


def test_unknown_provider_returns_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert create_legacy_llm_client("nonsense", "m") is None


def test_none_provider_returns_none(monkeypatch):
    assert create_legacy_llm_client("none", "m") is None


def test_missing_openai_key_returns_none(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert create_legacy_llm_client("openai", "gpt-4o") is None


def test_missing_anthropic_key_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert create_legacy_llm_client("anthropic", "claude-sonnet-4-5") is None


def test_unavailable_sdk_degrades_to_none(monkeypatch):
    # Contract: an unavailable provider SDK falls back to offline. The
    # mechanism to make the import fail is a test detail, not the contract.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setitem(sys.modules, "openai", None)
    assert create_legacy_llm_client("openai", "gpt-4o") is None


def test_provider_error_degrades_to_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    class _Adapter:
        profile = _Profile()

        def create_llm_callable(self, model, credential):
            raise ProviderUnavailableError("pip install 'pdf2epub[openai]'")

    monkeypatch.setattr(compat, "build_registry", lambda: _registry_returning(_Adapter()))
    assert create_legacy_llm_client("openai", "gpt-4o") is None


def test_non_provider_errors_propagate(monkeypatch):
    # Adapters normalize SDK failures; the bridge must NOT swallow
    # arbitrary exceptions (that would hide programming errors).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    class _Adapter:
        profile = _Profile()

        def create_llm_callable(self, model, credential):
            raise RuntimeError("programming error")

    monkeypatch.setattr(compat, "build_registry", lambda: _registry_returning(_Adapter()))
    with pytest.raises(RuntimeError):
        create_legacy_llm_client("openai", "gpt-4o")


def test_valid_key_and_sdk_returns_a_working_callable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

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
                            content='{"xhtml_pages": ["<p>ok</p>"]}'
                        )
                    )
                ]
            )

    module = types.ModuleType("openai")
    module.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", module)

    client = create_legacy_llm_client("openai", "gpt-4o")
    assert callable(client)
    assert client("SYS", "payload") == '{"xhtml_pages": ["<p>ok</p>"]}'
