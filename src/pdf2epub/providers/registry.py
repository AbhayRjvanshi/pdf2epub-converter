"""Provider registry.

Construction is profile-driven: :func:`build_registry` instantiates the
right API-style adapter per catalog profile, so adding a provider that
speaks an existing API family requires a catalog entry and nothing else.
``register`` remains for non-profile residents ("none") and test-time
residents. A duplicate ``provider_id`` fails at build time, and an
unknown ``api_style`` is the only event that justifies new adapter code.
"""

from __future__ import annotations

from .base import ProviderAdapter


class Registry:
    """Known provider adapters, keyed by provider_id."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        if adapter.provider_id in self._adapters:
            raise ValueError(
                f"duplicate provider registration: {adapter.provider_id!r}"
            )
        self._adapters[adapter.provider_id] = adapter

    def get(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError:
            raise KeyError(
                f"unknown provider {provider_id!r}; "
                f"known: {sorted(self._adapters)}"
            ) from None

    def list(self, *, user_facing_only: bool = True) -> list[ProviderAdapter]:
        adapters = list(self._adapters.values())
        if user_facing_only:
            adapters = [a for a in adapters if getattr(a, "user_facing", True)]
        return adapters


def build_registry(profiles=None) -> Registry:
    """Build the production registry from profiles (data -> adapters)."""
    from .anthropic_style import AnthropicStyleAdapter
    from .catalog import PROFILES
    from .nvidia_style import NvidiaStyleAdapter
    from .offline import OfflineProvider
    from .openai_style import OpenAIStyleAdapter

    api_styles = {
        "openai": OpenAIStyleAdapter,
        "anthropic": AnthropicStyleAdapter,
        "nvidia": NvidiaStyleAdapter,
    }

    registry = Registry()
    registry.register(OfflineProvider())
    for profile in profiles if profiles is not None else PROFILES:
        adapter_cls = api_styles.get(profile.api_style)
        if adapter_cls is None:
            raise ValueError(
                f"no adapter for api_style {profile.api_style!r} "
                f"(provider {profile.provider_id!r}); a new API family "
                "is the one event that justifies a new adapter implementation"
            )
        registry.register(adapter_cls(profile))
    return registry
