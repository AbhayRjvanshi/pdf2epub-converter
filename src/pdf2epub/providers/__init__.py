"""Tier 2 model provider adapters: contract, normalized errors, profiles.

Real OpenAI/Anthropic adapters implement the contract; OpenAI-compatible
services are data profiles over them. The registry is built from the
catalog, so adding a provider in a known API family is a catalog entry.
"""

from .base import LLMClient, ProviderAdapter
from .errors import (
    CredentialError,
    ModelNotFoundError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
    error_from_status,
    extract_retry_after,
    map_sdk_error,
    normalize_error,
    redact_secret,
)
from .models import ModelCapabilities, ModelDefinition
from .mock import MockProvider
from .offline import OfflineProvider
from .profile import CompatOptions, ProviderProfile
from .registry import Registry, build_registry
from .requirements import (
    ModelResolution,
    check_model_for_routes,
    resolve_model,
    supports_digest,
    supports_vision,
)

__all__ = [
    "LLMClient",
    "ProviderAdapter",
    "ProviderError",
    "CredentialError",
    "ProviderUnavailableError",
    "ModelNotFoundError",
    "ProviderRequestError",
    "ProviderResponseError",
    "error_from_status",
    "extract_retry_after",
    "map_sdk_error",
    "normalize_error",
    "redact_secret",
    "ModelCapabilities",
    "ModelDefinition",
    "MockProvider",
    "OfflineProvider",
    "CompatOptions",
    "ProviderProfile",
    "Registry",
    "build_registry",
    "ModelResolution",
    "check_model_for_routes",
    "resolve_model",
    "supports_digest",
    "supports_vision",
]
