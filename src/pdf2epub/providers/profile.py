"""Provider profiles: one provider endpoint described as data.

A profile is everything an API-style adapter needs to talk to a specific
endpoint. Adding a provider that speaks an existing API family ("openai"
or "anthropic") means adding a profile to the catalog -- no new code. A
new adapter implementation is justified only by a genuinely new wire
contract; that is the invariant this layer exists to enforce.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ModelDefinition


@dataclass(frozen=True)
class CompatOptions:
    """Mechanical wire-level differences between "compatible" endpoints."""

    extra_headers: dict[str, str] = field(default_factory=dict)
    supports_json_mode: bool = True  # False -> omit response_format; the prompt
                                     # plus the engine's fence-stripping carry it
    model_id_prefix: str = ""       # slug prefix some providers require
                                     # (e.g. "openai/" on aggregators)

    def with_prefix(self, model_id: str) -> str:
        return f"{self.model_id_prefix}{model_id}"


@dataclass(frozen=True)
class ProviderProfile:
    """One provider endpoint as pure data."""

    provider_id: str
    display_name: str
    api_style: str          # "openai" | "anthropic" | "nvidia"
    credential_env_var: str  # Phase 5 credential resolution reads this
    base_url: str | None = None       # None -> the provider's own default
    allow_generic_key: bool = False   # PDF2EPUB_API_KEY honoured only when True
    compat: CompatOptions = field(default_factory=CompatOptions)
    models: tuple[ModelDefinition, ...] = ()
    user_facing: bool = True  # only True entries appear in /provider lists
    client_dependency: str | None = None  # importable SDK module (None -> none)
    install_extra: str | None = None      # pip extra that provides the SDK

    def sdk_install_hint(self) -> str:
        """The pip command installing this profile's client SDK ('' if none).

        The extra is the user-facing fact; which module it provides is the
        adapter's business. Providers sharing one SDK (openai + nvidia)
        keep separate extras so users install for the provider they chose.
        """
        if self.client_dependency is None:
            return ""
        if self.install_extra:
            return f"pip install 'pdf2epub[{self.install_extra}]'"
        return f"pip install {self.client_dependency}"
