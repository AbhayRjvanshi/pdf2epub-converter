"""Legacy permissive adapter factory (transitional bridge).

The legacy CLI has always degraded to offline mode on an unknown provider,
a missing key, or a missing SDK. The new application layer is strict
(decision #5); this bridge exists only so the legacy entry point keeps its
documented permissive behavior until Phase 16 deletes it.

Policy only: provider -> credential lookup -> adapter construction ->
permissive fallback. It contains no provider-specific wire code -- the
Phase 4 adapters own that, and they own SDK error normalization too, so
this module catches ``ProviderError`` only and never broad ``Exception``
(programming errors must stay visible).
"""

from __future__ import annotations

import logging
import os

from .base import LLMClient
from .errors import ProviderError
from .registry import build_registry

log = logging.getLogger("pdf2epub.providers.compat")

# Exactly the providers the legacy CLI historically supported. Deliberately
# not derived from the registry, so the bridge never silently inherits
# future catalog additions and stays decoupled from Phase 16 removals.
_LEGACY_PROVIDERS = ("openai", "anthropic")


def create_legacy_llm_client(provider: str, model: str) -> LLMClient | None:
    """Permissive: unknown provider / missing key / missing SDK -> None.

    Mirrors ``engine.create_llm_client_adapter``'s long-standing contract so
    the legacy entry point and its tests keep working unchanged.
    """
    if provider not in _LEGACY_PROVIDERS:
        log.error(
            "Unknown provider %r - Tier 2 runs in offline fallback mode.", provider
        )
        return None

    adapter = build_registry().get(provider)
    api_key = os.getenv(adapter.profile.credential_env_var)
    if not api_key:
        log.warning(
            "No %s in environment - Tier 2 runs in offline fallback mode.",
            adapter.profile.credential_env_var,
        )
        return None

    try:
        return adapter.create_llm_callable(model, api_key)
    except ProviderError as exc:
        # Adapters normalize SDK failures into ProviderError; the permissive
        # fallback preserves the legacy contract. Broad Exception is
        # intentionally not caught (normalization belongs to the adapters).
        log.error("%s (falling back to offline mode)", exc)
        return None
