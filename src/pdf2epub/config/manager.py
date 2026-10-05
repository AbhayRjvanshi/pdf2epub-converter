"""Versioned, atomic, secret-free application configuration.

``load()`` is read-only and never raises for file states: a missing,
empty, corrupt or future-versioned file degrades to in-memory defaults
with a warning. ``save()`` merges explicit updates into the file
atomically (unique tmp file + ``os.replace``, cleaned up on failure) and
never materializes sections the caller did not set -- a missing
``[provider]`` key means "follow the default" (decision #5).

Migrations run in memory only; ``load()`` performs zero filesystem
mutations, so read-only runs (--help, --version, unprivileged execution)
stay side-effect free.

The schema has no secret-bearing fields: credentials live in environment
variables and the OS keyring (``config/credentials.py``), and tests
enforce both the structure and the serialized output stay that way.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from . import paths

log = logging.getLogger("pdf2epub.config.manager")

CURRENT_SCHEMA_VERSION = 1

# AppConfig field -> canonical (toml section, key)
TOML_MAP: dict[str, tuple[str, str]] = {
    "validators_notice": ("application", "validators_notice"),
    "provider_name": ("provider", "name"),
    "conversion_model": ("provider", "conversion_model"),
    "epubcheck_enabled": ("validator", "epubcheck"),
    "ace_enabled": ("validator", "ace"),
    "output_directory": ("defaults", "output_directory"),
    "cache_dir": ("paths", "cache_dir"),
}

_SECTION_LOOKUP: dict[str, dict[str, str]] = {}
for _field, (_section, _key) in TOML_MAP.items():
    _SECTION_LOOKUP.setdefault(_section, {})[_key] = _field

_FIELD_TYPES: dict[str, type] = {
    "validators_notice": str,
    "provider_name": str,
    "conversion_model": str,
    "epubcheck_enabled": bool,
    "ace_enabled": bool,
    "output_directory": str,
    "cache_dir": str,
}

# Optional fields may be explicitly unset by saving None.
_OPTIONAL_FIELDS = {"provider_name", "conversion_model", "cache_dir"}


@dataclass(frozen=True)
class AppConfig:
    """The application configuration state.

    ``provider_name``/``conversion_model`` of ``None`` mean "follow the
    default"; unknown or retired ids load unchanged -- judging them is
    Phase 7's job (registry + resolve_model), not the manager's.
    """

    schema_version: int = CURRENT_SCHEMA_VERSION
    validators_notice: str = "always"  # "always" | "never" (Phase 13 onboarding)
    provider_name: str | None = None
    conversion_model: str | None = None
    epubcheck_enabled: bool = True  # feeds the S1 validators seam (Phase 9)
    ace_enabled: bool = True
    output_directory: str = "."  # REPL default export dir (Phase 12)
    cache_dir: str | None = None  # None -> paths.cache_dir()

    @property
    def resolved_cache_dir(self) -> Path:
        """Explicit cache_dir when configured, the platform default otherwise."""
        return Path(self.cache_dir) if self.cache_dir else paths.cache_dir()


def _migrate_legacy_to_v1(raw: dict) -> dict:
    """Stamp schema_version on files written before versioning existed."""
    raw.setdefault("schema_version", 1)
    return raw


_MIGRATIONS: dict[int, Any] = {1: _migrate_legacy_to_v1}


def _normalize_updates(
    updates: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Accept flat field names and sectioned dicts; reject everything else.

    Wrong types and None-for-required are caller bugs and raise
    ValueError, mirroring the credential resolver's contract-misuse rule.
    """
    to_set: dict[str, Any] = {}
    to_unset: list[str] = []

    def place(field: str, value: Any, label: str) -> None:
        if value is None:
            if field not in _OPTIONAL_FIELDS:
                raise ValueError(f"{label} cannot be None")
            to_unset.append(field)
            return
        expected = _FIELD_TYPES[field]
        if not isinstance(value, expected):
            raise ValueError(
                f"{label} expects {expected.__name__}, "
                f"got {type(value).__name__}"
            )
        to_set[field] = value

    for key, value in dict(updates).items():
        if key in TOML_MAP:
            place(key, value, key)
        elif key in _SECTION_LOOKUP:
            if not isinstance(value, Mapping):
                raise ValueError(f"section {key!r} requires a mapping")
            for sub_key, sub_value in value.items():
                field = _SECTION_LOOKUP[key].get(sub_key)
                if field is None:
                    raise ValueError(f"unknown config key: {key}.{sub_key}")
                place(field, sub_value, f"{key}.{sub_key}")
        else:
            raise ValueError(f"unknown config key: {key!r}")
    return to_set, to_unset


class ConfigManager:
    """Load/save the user's config.toml. Injectable path; never global."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = (
            Path(config_path) if config_path is not None else paths.config_file()
        )

    def path(self) -> Path:
        return self._path

    # -- read --------------------------------------------------------------
    def _read_raw(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            raw = tomllib.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning(
                "ignoring unreadable config %s (%s); using defaults",
                self._path,
                type(exc).__name__,
            )
            return {}
        return raw if isinstance(raw, dict) else {}

    def _from_raw(self, raw: dict) -> AppConfig:
        version = raw.get("schema_version", 0)
        if not isinstance(version, int):
            log.warning(
                "config %s: non-integer schema_version; treating as legacy",
                self._path,
            )
            version = 0
        if version > CURRENT_SCHEMA_VERSION:
            log.warning(
                "config %s was written by a newer pdf2epub (schema %s > %s); "
                "known fields still apply",
                self._path,
                version,
                CURRENT_SCHEMA_VERSION,
            )
        else:
            for step in sorted(_MIGRATIONS):
                if version < step:
                    raw = _MIGRATIONS[step](raw)
                    version = step

        updates: dict[str, Any] = {"schema_version": version}
        for field_name, (section, key) in TOML_MAP.items():
            table = raw.get(section)
            if not isinstance(table, dict) or key not in table:
                continue
            value = table[key]
            expected = _FIELD_TYPES[field_name]
            if not isinstance(value, expected):
                log.warning(
                    "config %s: ignoring %s.%s (expected %s)",
                    self._path,
                    section,
                    key,
                    expected.__name__,
                )
                continue
            updates[field_name] = value
        # unknown sections/keys are ignored on purpose (forward compatibility)
        return AppConfig(**updates)

    def load(self) -> AppConfig:
        """Read the config; never writes, never raises for file states."""
        return self._from_raw(self._read_raw())

    # -- write -------------------------------------------------------------
    def save(self, updates: Mapping[str, Any]) -> AppConfig:
        """Merge explicit updates into the file atomically; return the result.

        Only what is explicitly set is materialized. A corrupt or missing
        file is replaced by a clean one built from defaults + updates.
        The file's schema_version is preserved (migrated files get the
        current version; files from a newer pdf2epub keep theirs).
        """
        raw = self._read_raw()
        to_set, to_unset = _normalize_updates(updates)

        for field_name, value in to_set.items():
            section, key = TOML_MAP[field_name]
            raw.setdefault(section, {})[key] = value
        for field_name in to_unset:
            section, key = TOML_MAP[field_name]
            table = raw.get(section)
            if isinstance(table, dict):
                table.pop(key, None)
                if not table:
                    raw.pop(section, None)

        raw["schema_version"] = self._from_raw(raw).schema_version
        self._atomic_write(raw)
        return self.load()

    def _atomic_write(self, raw: dict) -> None:
        """Windows-safe: unique sibling tmp file, replace, no strays.

        ``os.replace`` raises ``PermissionError`` on Windows when the
        destination has an open handle; the unique name avoids colliding
        tmp files between concurrent saves, and the ``finally`` cleanup
        removes the tmp file on any pre-replace failure.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.parent / (
            f"{self._path.name}.tmp.{os.getpid()}.{time.time_ns()}"
        )
        try:
            tmp.write_bytes(tomli_w.dumps(raw).encode("utf-8"))
            os.replace(tmp, self._path)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
