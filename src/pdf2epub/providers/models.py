"""Model descriptors for the provider contract.

Phase 3 lands the data shape so the :class:`~pdf2epub.providers.base.ProviderAdapter`
protocol is fully typed. Phase 4 enriches these with the curated static
catalog, route-specific capability requirements and lifecycle handling
(active / experimental / deprecated / retired).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelCapabilities:
    """What a model can accept and produce on the wire."""

    text_input: bool = True
    image_input: bool = False
    text_output: bool = True
    structured_output: bool = False  # JSON mode or equivalent, guaranteed
    max_context: int | None = None


@dataclass(frozen=True)
class ModelDefinition:
    """One model offered by one provider."""

    provider_id: str
    model_id: str
    display_name: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    # Lifecycle: active | experimental | deprecated | retired
    status: str = "active"
