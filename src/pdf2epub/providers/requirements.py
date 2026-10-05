"""Route-specific model capability requirements.

This module owns the mapping model-capabilities -> route support. Which
routes a *document* actually needs is owned by the Phase 7 preflight (fed
by the engine's routing report); this module never re-derives the
engine's vision-bypass policy, so the two cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import ModelDefinition

ALLOWED_ROUTES = frozenset({"digest", "vision"})


@dataclass(frozen=True)
class ModelResolution:
    """Result of looking a model id up against a provider's catalog.

    ``definition is None`` -> unknown model: proceed with the advisory
    warning (the catalog is not a gate; the wire id may still be valid).
    ``definition.status == "retired"`` -> known-retired: callers (Phase 6
    config) should require reselection.
    ``warning is None`` -> known and active.
    """

    definition: ModelDefinition | None
    warning: str | None


def supports_digest(model: ModelDefinition) -> bool:
    """Text-layout pages: text in, structured text out."""
    caps = model.capabilities
    return caps.text_input and caps.text_output and caps.structured_output


def supports_vision(model: ModelDefinition) -> bool:
    """Image pages: image in, structured text out."""
    caps = model.capabilities
    return caps.image_input and caps.text_output and caps.structured_output


def check_model_for_routes(
    model: ModelDefinition, required_routes: Iterable[str]
) -> list[str]:
    """Problems that make ``model`` unusable for ``required_routes``.

    Empty list = the model is usable. Callers own which routes a document
    needs; this function only answers the capability question.
    """
    problems: list[str] = []
    routes = set(required_routes)
    if "digest" in routes and not supports_digest(model):
        problems.append(
            f"model {model.model_id!r} cannot handle digest pages "
            "(needs text input, text output and structured output)"
        )
    if "vision" in routes and not supports_vision(model):
        problems.append(
            f"model {model.model_id!r} cannot handle vision pages "
            "(needs image input, text output and structured output)"
        )
    return problems


def resolve_model(provider, model_id: str) -> ModelResolution:
    """Advisory model lookup against the provider's static catalog."""
    for model in provider.resolve_models():
        if model.model_id == model_id:
            if model.status == "retired":
                return ModelResolution(
                    model,
                    f"model {model_id!r} is retired from the catalog; "
                    "reselection is recommended",
                )
            return ModelResolution(model, None)
    return ModelResolution(
        None,
        f"model {model_id!r} is not in provider {provider.provider_id!r}'s "
        "static catalog; proceeding without capability verification",
    )
