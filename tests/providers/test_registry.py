"""Phase 4: the registry is profile-driven - providers are data, not code."""

import json
import sys
import types

import pytest

from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.models import ModelCapabilities, ModelDefinition
from pdf2epub.providers.offline import OfflineProvider
from pdf2epub.providers.openai_style import OpenAIStyleAdapter
from pdf2epub.providers.profile import CompatOptions, ProviderProfile
from pdf2epub.providers.registry import Registry, build_registry


def test_default_registry_has_offline_and_both_real_providers():
    registry = build_registry()
    assert isinstance(registry.get("none"), OfflineProvider)
    assert isinstance(registry.get("openai"), OpenAIStyleAdapter)

    from pdf2epub.providers.anthropic_style import AnthropicStyleAdapter

    assert isinstance(registry.get("anthropic"), AnthropicStyleAdapter)


def test_user_facing_listing_hides_experimental_profiles():
    registry = build_registry()
    listed = {a.provider_id for a in registry.list()}
    assert "openrouter" not in listed
    assert {"none", "openai", "anthropic"} <= listed
    everything = {a.provider_id for a in registry.list(user_facing_only=False)}
    assert "openrouter" in everything


def test_unknown_provider_is_a_clean_keyerror_naming_knowns():
    registry = build_registry()
    with pytest.raises(KeyError) as excinfo:
        registry.get("nope")
    assert "nope" in str(excinfo.value)
    assert "openai" in str(excinfo.value)


def test_duplicate_registration_fails():
    registry = Registry()
    registry.register(OfflineProvider())
    with pytest.raises(ValueError):
        registry.register(OfflineProvider())


def test_duplicate_catalog_ids_fail_at_build_time():
    profile = PROFILES[0]
    with pytest.raises(ValueError):
        build_registry([profile, profile])


def test_unknown_api_style_fails_with_new_family_message():
    profile = ProviderProfile("weird", "Weird", "carrier-pigeon", "WEIRD_API_KEY")
    with pytest.raises(ValueError) as excinfo:
        build_registry([profile])
    assert "new API family" in str(excinfo.value)


_SYNTHETIC = ProviderProfile(
    provider_id="synthetic",
    display_name="Synthetic OpenAI-compatible",
    api_style="openai",
    credential_env_var="SYNTHETIC_API_KEY",
    base_url="https://synthetic.test/v1",
    allow_generic_key=True,
    compat=CompatOptions(
        extra_headers={"X-Probe": "1"},
        supports_json_mode=False,
        model_id_prefix="syn/",
    ),
    models=(
        ModelDefinition(
            provider_id="synthetic",
            model_id="syn-model",
            display_name="Syn Model",
            capabilities=ModelCapabilities(structured_output=True),
        ),
    ),
    user_facing=False,
)


def test_new_provider_in_known_family_is_data_only(monkeypatch):
    """The Phase 4 invariant, executed: a catalog entry and nothing else."""
    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured["create"] = kwargs
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(
                            content=json.dumps(
                                {"xhtml_pages": ["<p>synthetic ok</p>"]}
                            )
                        )
                    )
                ]
            )

    module = types.ModuleType("openai")
    module.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", module)

    registry = build_registry([_SYNTHETIC])
    adapter = registry.get("synthetic")
    assert adapter.provider_id == "synthetic"
    assert adapter.user_facing is False

    llm = adapter.create_llm_callable("syn-model", "sk-synth")
    raw = llm(
        "SYS",
        json.dumps(
            {
                "instruction": "x",
                "page_count": 1,
                "pages": [{"page_num": 1, "layout_digest": []}],
            }
        ),
    )
    assert "synthetic ok" in raw
    assert captured["init"]["base_url"] == "https://synthetic.test/v1"
    assert captured["init"]["default_headers"] == {"X-Probe": "1"}
    assert captured["create"]["model"] == "syn/syn-model"
    assert "response_format" not in captured["create"]
