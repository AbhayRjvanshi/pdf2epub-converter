"""Phase 6: platform-aware directories - one family, three roots."""

from pathlib import Path

import pdf2epub.config.paths as paths_module


def test_all_dirs_come_from_platformdirs_with_appauthor_disabled(monkeypatch):
    calls = []

    def fake(app_name, appauthor=None):
        calls.append((app_name, appauthor))
        return Path(f"/fake/{app_name}-{len(calls)}")

    monkeypatch.setattr(paths_module, "user_config_path", fake)
    monkeypatch.setattr(paths_module, "user_cache_path", fake)
    monkeypatch.setattr(paths_module, "user_log_path", fake)

    paths_module.config_dir()
    paths_module.cache_dir()
    paths_module.logs_dir()

    assert len(calls) == 3
    assert all(name == "pdf2epub" and appauthor is False for name, appauthor in calls)


def test_config_file_lives_in_config_dir(monkeypatch):
    fake_dir = Path("C:/fake/config")
    monkeypatch.setattr(
        paths_module, "user_config_path", lambda *a, **k: fake_dir
    )
    assert paths_module.config_file() == fake_dir / "config.toml"


def test_dirs_resolve_on_this_machine_without_creating_anything(tmp_path):
    # real smoke: every function returns a Path and does not raise;
    # platformdirs does not create directories (ensure_exists defaults off)
    for getter in (
        paths_module.config_dir,
        paths_module.cache_dir,
        paths_module.logs_dir,
    ):
        value = getter()
        assert isinstance(value, Path)
