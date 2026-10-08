"""Phase 4: profiles are frozen data with mechanical compat helpers."""

import sys
from pathlib import Path

import pytest

from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.profile import CompatOptions, ProviderProfile


def test_profile_defaults_are_conservative():
    profile = ProviderProfile(
        provider_id="x",
        display_name="X",
        api_style="openai",
        credential_env_var="X_API_KEY",
    )
    assert profile.base_url is None
    assert profile.allow_generic_key is False
    assert profile.models == ()
    assert profile.user_facing is True
    assert profile.compat.supports_json_mode is True
    assert profile.compat.model_id_prefix == ""
    assert profile.client_dependency is None
    assert profile.install_extra is None
    assert profile.sdk_install_hint() == ""


def test_compat_prefixing():
    assert CompatOptions().with_prefix("gpt-4o") == "gpt-4o"
    prefixed = CompatOptions(model_id_prefix="openai/")
    assert prefixed.with_prefix("gpt-4o") == "openai/gpt-4o"


def test_profiles_are_frozen():
    profile = ProviderProfile("x", "X", "openai", "X_API_KEY")
    with pytest.raises(AttributeError):
        profile.provider_id = "y"


def test_compat_options_are_frozen():
    compat = CompatOptions()
    with pytest.raises(AttributeError):
        compat.supports_json_mode = False


def test_catalog_declares_sdk_dependency_metadata():
    by_id = {p.provider_id: p for p in PROFILES}
    assert by_id["openai"].client_dependency == "openai"
    assert by_id["openai"].install_extra == "openai"
    # nvidia shares the openai client SDK but keeps its own user-facing extra
    assert by_id["nvidia"].client_dependency == "openai"
    assert by_id["nvidia"].install_extra == "nvidia"
    assert by_id["anthropic"].client_dependency == "anthropic"
    assert by_id["anthropic"].install_extra == "anthropic"
    assert by_id["openrouter"].client_dependency == "openai"
    assert by_id["openai"].sdk_install_hint() == "pip install 'pdf2epub[openai]'"
    assert by_id["nvidia"].sdk_install_hint() == "pip install 'pdf2epub[nvidia]'"
    assert by_id["anthropic"].sdk_install_hint() == "pip install 'pdf2epub[anthropic]'"


def test_every_install_extra_declared_by_a_profile_exists_in_pyproject():
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    extras = tomllib.loads(pyproject.read_text(encoding="utf-8"))[
        "project"
    ]["optional-dependencies"]
    for profile in PROFILES:
        if profile.install_extra is not None:
            assert profile.install_extra in extras, profile.provider_id
            assert extras[profile.install_extra], profile.provider_id
