"""Phase 4: profiles are frozen data with mechanical compat helpers."""

import pytest

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
