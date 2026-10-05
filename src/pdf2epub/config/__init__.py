"""User configuration and credential handling."""

from .credentials import (
    GENERIC_ENV_VAR,
    KEYRING_SERVICE,
    CredentialResolutionResult,
    keyring_delete,
    keyring_store,
    resolve_credential,
    resolve_for_profile,
)
from .manager import AppConfig, ConfigManager, CURRENT_SCHEMA_VERSION, TOML_MAP
from .paths import cache_dir, config_dir, config_file, logs_dir

__all__ = [
    "GENERIC_ENV_VAR",
    "KEYRING_SERVICE",
    "CredentialResolutionResult",
    "keyring_delete",
    "keyring_store",
    "resolve_credential",
    "resolve_for_profile",
    "AppConfig",
    "ConfigManager",
    "CURRENT_SCHEMA_VERSION",
    "TOML_MAP",
    "cache_dir",
    "config_dir",
    "config_file",
    "logs_dir",
]
