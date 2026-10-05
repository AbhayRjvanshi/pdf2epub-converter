"""Credential resolution: one honest, headless-safe security boundary.

Resolution is local-only and never raises for runtime conditions: callers
(Phase 7 validation, Phase 9 service) turn an ``unavailable`` result into
the application's configuration error, so policy lives above this module.

The chain honours decision #11: explicit secret -> provider-specific
environment variable -> generic PDF2EPUB_API_KEY (only for providers that
opt in) -> OS keyring -> unavailable.

Keyring is an optional dependency behind an import guard; any backend
failure (headless Linux, locked keychains, missing dbus) degrades to
``unavailable`` or ``False`` with a debug-level log naming only the
exception type. Credential material never reaches logs, warnings or
errors.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Literal, Mapping

log = logging.getLogger("pdf2epub.config.credentials")

GENERIC_ENV_VAR = "PDF2EPUB_API_KEY"
KEYRING_SERVICE = "pdf2epub"

Source = Literal[
    "explicit",
    "environment",
    "generic_environment",
    "keyring",
    "unavailable",
]


@dataclass(frozen=True)
class CredentialResolutionResult:
    """Outcome of resolving one provider's credential.

    ``warning`` is human-visible and never contains the credential: it
    notes honest oddities (an ignored empty explicit secret, generic-key
    use per opt-in, an offline provider that needs no credential).
    """

    credential: str | None
    source: Source
    provider_id: str
    warning: str | None = None


def resolve_credential(
    provider_id: str,
    *,
    env_var: str,
    allow_generic_key: bool = False,
    explicit_secret: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialResolutionResult:
    """Resolve the credential for one provider. Local-only, never raises.

    Runtime conditions (absent values, keyring failures) are reported in
    the result; only contract misuse (empty ``provider_id``/``env_var``)
    raises ``ValueError`` -- that is a caller bug, not a runtime state.
    """
    if not provider_id:
        raise ValueError("provider_id is required")
    if provider_id == "none":
        return CredentialResolutionResult(
            None, "unavailable", "none", "offline provider needs no credential"
        )
    if not env_var:
        raise ValueError("env_var is required")

    environ = os.environ if environ is None else environ
    pending_warning: str | None = None

    if explicit_secret is not None:
        stripped = explicit_secret.strip()
        if stripped:
            return CredentialResolutionResult(
                stripped, "explicit", provider_id, None
            )
        pending_warning = "explicit secret was empty; ignored"

    provider_value = (environ.get(env_var) or "").strip()
    if provider_value:
        return CredentialResolutionResult(
            provider_value, "environment", provider_id, None
        )

    if allow_generic_key and env_var != GENERIC_ENV_VAR:
        generic_value = (environ.get(GENERIC_ENV_VAR) or "").strip()
        if generic_value:
            return CredentialResolutionResult(
                generic_value,
                "generic_environment",
                provider_id,
                f"using generic {GENERIC_ENV_VAR} for provider "
                f"{provider_id!r} (per provider opt-in)",
            )

    secret = _keyring_get(provider_id)
    if secret:
        return CredentialResolutionResult(
            secret.strip(), "keyring", provider_id, None
        )

    return CredentialResolutionResult(
        None, "unavailable", provider_id, pending_warning
    )


def resolve_for_profile(
    profile,
    *,
    explicit_secret: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialResolutionResult:
    """Ergonomics wrapper over :func:`resolve_credential`.

    Deliberately duck-typed: any object with ``provider_id``,
    ``credential_env_var`` and ``allow_generic_key`` attributes works, so
    this module imports nothing from the providers layer. The offline
    provider (which has no credential facts) resolves to its clean
    "needs no credential" result before any attribute is touched.
    """
    return resolve_credential(
        getattr(profile, "provider_id", ""),
        env_var=getattr(profile, "credential_env_var", ""),
        allow_generic_key=bool(getattr(profile, "allow_generic_key", False)),
        explicit_secret=explicit_secret,
        environ=environ,
    )


# ---------------------------------------------------------------------------
# Keyring boundary: one scheme, one error envelope, for read/store/delete.
# All three operations share service/username constants and the same
# catch-everything degradation so no future flow can grow a second path.
# ---------------------------------------------------------------------------


def _keyring_module():
    """The keyring module when installed, else None. No import side effects."""
    if find_spec("keyring") is None:
        return None
    import keyring

    return keyring


def _keyring_get(provider_id: str) -> str | None:
    module = _keyring_module()
    if module is None:
        log.debug("keyring not installed; no credential for %s", provider_id)
        return None
    try:
        return module.get_password(KEYRING_SERVICE, provider_id)
    except Exception as exc:
        log.debug(
            "keyring read failed for %s: %s", provider_id, type(exc).__name__
        )
        return None


def keyring_store(provider_id: str, secret: str) -> bool:
    """Persist a provider credential in the OS keyring. Best-effort."""
    module = _keyring_module()
    if module is None:
        log.debug("keyring not installed; cannot store credential for %s", provider_id)
        return False
    try:
        module.set_password(KEYRING_SERVICE, provider_id, secret)
        return True
    except Exception as exc:
        log.debug(
            "keyring store failed for %s: %s", provider_id, type(exc).__name__
        )
        return False


def keyring_delete(provider_id: str) -> bool:
    """Remove a stored credential. Best-effort and idempotent."""
    module = _keyring_module()
    if module is None:
        log.debug("keyring not installed; cannot delete credential for %s", provider_id)
        return False
    try:
        module.delete_password(KEYRING_SERVICE, provider_id)
        return True
    except Exception as exc:
        # Some backends raise when the entry is already gone; idempotency
        # matters more than telling the caller which call removed it.
        log.debug(
            "keyring delete for %s: %s", provider_id, type(exc).__name__
        )
        return False
