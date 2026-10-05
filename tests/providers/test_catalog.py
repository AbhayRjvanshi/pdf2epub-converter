"""Phase 4: catalog integrity - the data is logic, it gets tests."""

from pdf2epub.providers.catalog import PROFILES
from pdf2epub.providers.requirements import supports_digest, supports_vision

ALLOWED_STATUSES = {"active", "experimental", "deprecated", "retired"}


def _by_id(provider_id):
    return next(p for p in PROFILES if p.provider_id == provider_id)


def test_catalog_has_user_facing_openai_and_anthropic():
    ids = {p.provider_id for p in PROFILES if p.user_facing}
    assert {"openai", "anthropic"} <= ids


def test_every_profile_declares_a_known_api_style():
    for profile in PROFILES:
        assert profile.api_style in {"openai", "anthropic"}, profile.provider_id


def test_every_model_belongs_to_its_profile():
    for profile in PROFILES:
        for model in profile.models:
            assert model.provider_id == profile.provider_id
            assert model.status in ALLOWED_STATUSES


def test_shipped_defaults_cover_both_routes():
    openai = _by_id("openai")
    assert openai.models[0].model_id == "gpt-4o"
    for model in openai.models:
        assert supports_digest(model) and supports_vision(model)

    claude = _by_id("anthropic").models[0]
    assert claude.model_id == "claude-sonnet-4-5"
    assert supports_digest(claude) and supports_vision(claude)


def test_openrouter_is_a_hidden_data_only_entry():
    openrouter = _by_id("openrouter")
    assert openrouter.user_facing is False
    assert openrouter.api_style == "openai"
    assert openrouter.base_url == "https://openrouter.ai/api/v1"
    assert openrouter.allow_generic_key is True
    assert openrouter.compat.supports_json_mode is False
    assert openrouter.compat.model_id_prefix == "openai/"
    assert "HTTP-Referer" in openrouter.compat.extra_headers
    assert openrouter.models == ()
