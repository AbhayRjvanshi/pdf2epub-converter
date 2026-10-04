"""The provider contract.

The application layer knows this interface and nothing else about a
provider. The engine keeps consuming the plain callable it has always
consumed; its shape is re-declared here so the provider layer never needs
to import the engine (layer isolation is enforced by test, not convention).
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from .models import ModelDefinition

# Byte-identical to the engine's Tier-2 client contract:
#     client(system_prompt, user_payload, image_b64 | None) -> raw string
LLMClient = Callable[[str, str, str | None], str]


@runtime_checkable
class ProviderAdapter(Protocol):
    """What every provider must offer the application layer."""

    provider_id: str

    def resolve_models(self) -> list[ModelDefinition]:
        """Models this provider offers (from the static catalog in v1)."""
        ...

    def validate_credentials(self, credential: str) -> bool:
        """Check that ``credential`` is accepted.

        NETWORK CALL: runs only when the user explicitly asks for
        verification, never at application startup.
        """
        ...

    def create_llm_callable(self, model_id: str, credential: str) -> LLMClient:
        """Build the prompt-in, text-out function the engine consumes.

        Must return the bare engine callable -- no wrapper stacking. SDK
        exceptions must not escape: map them via
        :func:`~pdf2epub.providers.errors.error_from_status` or
        :func:`~pdf2epub.providers.errors.normalize_error`.
        """
        ...
