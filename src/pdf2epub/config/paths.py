"""Platform-aware application directories.

One function family for config/cache/log locations; every consumer goes
through these, so relocating or re-platforming later is a one-file change.
platformdirs handles the Windows roaming/local split (small human-editable
config in Roaming, high-volume ephemeral caches in Local -- which roaming
profiles must not sync), XDG on Linux and ~/Library on macOS.

``appauthor=False`` avoids the redundant vendor subfolder platformdirs
would otherwise insert (AppData/Roaming/pdf2epub/pdf2epub). The
``user_*_path`` variants return ``pathlib.Path`` objects and do not
create anything; callers create on demand.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_log_path

APP_NAME = "pdf2epub"


def config_dir() -> Path:
    """Small, human-editable configuration (config.toml lives here)."""
    return user_config_path(APP_NAME, appauthor=False)


def cache_dir() -> Path:
    """Bulk, ephemeral cache data (LLM response cache, spool artefacts)."""
    return user_cache_path(APP_NAME, appauthor=False)


def logs_dir() -> Path:
    """Log files."""
    return user_log_path(APP_NAME, appauthor=False)


def config_file() -> Path:
    return config_dir() / "config.toml"
