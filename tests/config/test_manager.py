"""Phase 6: the config manager - load never raises, save never strays."""

import dataclasses
import logging
from pathlib import Path

import pytest

import pdf2epub.config.manager as manager_module
import pdf2epub.config.paths as paths_module
from pdf2epub.config.manager import (
    CURRENT_SCHEMA_VERSION,
    TOML_MAP,
    AppConfig,
    ConfigManager,
    _FIELD_TYPES,
)

LOGGER = "pdf2epub.config.manager"


def test_missing_file_loads_pure_defaults_without_creating_anything(tmp_path):
    path = tmp_path / "config.toml"
    config = ConfigManager(path).load()
    assert config == AppConfig()
    assert not path.exists()  # reads never write


def test_corrupt_toml_degrades_to_defaults_with_warning(tmp_path, caplog):
    path = tmp_path / "config.toml"
    path.write_text("this is [ not toml", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        config = ConfigManager(path).load()
    assert config == AppConfig()
    assert any("unreadable" in r.getMessage() for r in caplog.records)


def test_empty_file_loads_defaults(tmp_path):
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    assert ConfigManager(tmp_path / "config.toml").load() == AppConfig()


def test_save_and_roundtrip(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    config = manager.save({"provider_name": "openai", "epubcheck_enabled": False})
    assert config.provider_name == "openai"
    assert config.epubcheck_enabled is False
    assert ConfigManager(tmp_path / "config.toml").load() == config


def test_first_save_writes_only_explicit_keys_and_schema_version(tmp_path):
    path = tmp_path / "config.toml"
    ConfigManager(path).save({"validators_notice": "never"})
    text = path.read_text(encoding="utf-8")
    assert "schema_version" in text
    assert "validators_notice" in text
    # never materialize what was not explicitly set (decision #5)
    assert "[provider]" not in text
    assert ConfigManager(path).load().provider_name is None


def test_merge_save_preserves_untouched_keys(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.save({"provider_name": "openai"})
    manager.save({"ace_enabled": False})
    loaded = manager.load()
    assert loaded.provider_name == "openai"
    assert loaded.ace_enabled is False
    assert loaded.epubcheck_enabled is True


def test_save_accepts_sectioned_form(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    config = manager.save(
        {"provider": {"name": "anthropic", "conversion_model": "claude-sonnet-4-5"}}
    )
    assert config.provider_name == "anthropic"
    assert config.conversion_model == "claude-sonnet-4-5"


def test_saving_none_unsets_optional_keys(tmp_path):
    path = tmp_path / "config.toml"
    manager = ConfigManager(path)
    manager.save({"provider_name": "openai"})
    config = manager.save({"provider_name": None})
    assert config.provider_name is None
    assert "[provider]" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        manager.save({"validators_notice": None})


def test_unknown_or_wrong_typed_updates_raise_value_error(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    with pytest.raises(ValueError):
        manager.save({"nope": "x"})
    with pytest.raises(ValueError):
        manager.save({"provider": {"nope": "x"}})
    with pytest.raises(ValueError):
        manager.save({"epubcheck_enabled": "yes"})


def test_wrong_typed_file_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[validator]\nepubcheck = "yes"\n', encoding="utf-8")
    assert ConfigManager(path).load().epubcheck_enabled is True


def test_unknown_file_sections_are_ignored_and_survive_a_save(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[future_section]\nkey = "value"\n[provider]\nname = "openai"\n',
        encoding="utf-8",
    )
    manager = ConfigManager(path)
    assert manager.load().provider_name == "openai"  # unknown section ignored
    manager.save({"ace_enabled": False})
    # unknown sections survive a rewrite (forward compatibility)
    assert "future_section" in path.read_text(encoding="utf-8")


def test_unknown_provider_ids_pass_through_unchanged(tmp_path):
    path = tmp_path / "config.toml"
    ConfigManager(path).save(
        {"provider_name": "martian-modem", "conversion_model": "unknown-future-model"}
    )
    config = ConfigManager(path).load()
    assert config.provider_name == "martian-modem"
    assert config.conversion_model == "unknown-future-model"
    # judging ids is Phase 7's job (registry + resolve_model), not the manager's


def test_legacy_file_without_schema_version_is_migrated_in_memory(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[provider]\nname = "openai"\n', encoding="utf-8")
    config = ConfigManager(path).load()
    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.provider_name == "openai"
    # load() is read-only: the on-disk file is untouched
    assert "schema_version" not in path.read_text(encoding="utf-8")
    # and a save stamps the migrated version
    ConfigManager(path).save({"ace_enabled": False})
    assert f"schema_version = {CURRENT_SCHEMA_VERSION}" in path.read_text(
        encoding="utf-8"
    )


def test_future_schema_version_loads_without_crashing(tmp_path, caplog):
    path = tmp_path / "config.toml"
    future = CURRENT_SCHEMA_VERSION + 5
    path.write_text(
        f'schema_version = {future}\n[provider]\nname = "openai"\n',
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        config = ConfigManager(path).load()
    assert config.provider_name == "openai"
    assert config.schema_version == future  # preserved, not downgraded
    assert any("newer pdf2epub" in r.getMessage() for r in caplog.records)
    # and saving does not downgrade a future version either
    ConfigManager(path).save({"ace_enabled": False})
    assert f"schema_version = {future}" in path.read_text(encoding="utf-8")


def test_failed_write_leaves_original_file_and_no_tmp_strays(
    tmp_path, monkeypatch
):
    path = tmp_path / "config.toml"
    manager = ConfigManager(path)
    manager.save({"provider_name": "openai"})
    before = path.read_text(encoding="utf-8")

    def explode(raw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(manager_module.tomli_w, "dumps", explode)
    with pytest.raises(RuntimeError):
        manager.save({"ace_enabled": False})
    assert path.read_text(encoding="utf-8") == before
    assert list(tmp_path.glob("*.tmp*")) == []


def test_saving_over_a_corrupt_file_rewrites_it_clean(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("garbage ]]]", encoding="utf-8")
    config = ConfigManager(path).save({"provider_name": "openai"})
    assert ConfigManager(path).load() == config
    assert "garbage" not in path.read_text(encoding="utf-8")


def test_config_schema_has_no_secret_bearing_fields():
    for field in dataclasses.fields(AppConfig):
        name = field.name.lower()
        assert not any(
            marker in name for marker in ("key", "secret", "token", "password")
        ), field.name


def test_full_save_never_contains_credentials(tmp_path, monkeypatch):
    secret = "sk-live-config-hygiene"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    path = tmp_path / "config.toml"
    ConfigManager(path).save(
        {
            "provider_name": "openai",
            "conversion_model": "gpt-4o",
            "validators_notice": "never",
            "epubcheck_enabled": True,
            "ace_enabled": False,
            "output_directory": ".",
            "cache_dir": str(tmp_path / "cache"),
        }
    )
    text = path.read_text(encoding="utf-8")
    assert secret not in text
    assert "api_key" not in text.lower()


def test_resolved_cache_dir_prefers_explicit_then_platform_default(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        paths_module, "user_cache_path", lambda *a, **k: Path("/fake/cache")
    )
    explicit = AppConfig(cache_dir=str(tmp_path / "custom"))
    assert explicit.resolved_cache_dir == tmp_path / "custom"
    assert AppConfig().resolved_cache_dir == Path("/fake/cache")


def test_toml_map_and_field_types_stay_in_sync():
    assert set(TOML_MAP) == set(_FIELD_TYPES)
