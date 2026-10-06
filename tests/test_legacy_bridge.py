"""Phase 11: the legacy permissive bridge (providers.compat).

The bridge exists only for the legacy CLI's documented fallback contract:
unknown provider / missing key / missing SDK -> None. It delegates to the
same Phase 4 adapters the application layer uses, so it carries no wire
code of its own. The engine-SDK-free pins prove the engine's only edge to
the provider layer is this single lazy delegation.
"""

import os
import subprocess
import sys
import types
from pathlib import Path

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


# -- engine SDK-free pins (one lazy delegation edge is the sole exception) ---

def test_importing_the_engine_pulls_no_sdk_and_no_providers():
    src = Path(__file__).resolve().parent.parent / "src"
    code = (
        "import sys, importlib;"
        "importlib.import_module('pdf2epub.engine.driver');"
        "bad = [m for m in ('openai', 'anthropic', 'pdf2epub.providers')"
        "       if m in sys.modules"
        "       or any(x.startswith(m + '.') for x in sys.modules)];"
        "sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_engine_source_contains_no_sdk_imports():
    import pdf2epub.engine as engine_pkg

    engine_dir = Path(engine_pkg.__file__).parent
    for path in engine_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import openai" not in text, path.name
        assert "import anthropic" not in text, path.name
