"""Tier 2 model provider adapters: contract, normalized errors, test providers.

Real OpenAI/Anthropic adapters arrive in Phase 4 as implementations of this
contract; OpenAI-compatible services arrive as data profiles over them.
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
    normalize_error,
    redact_secret,
)
from .models import ModelCapabilities, ModelDefinition
from .mock import MockProvider
from .offline import OfflineProvider

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
    "normalize_error",
    "redact_secret",
    "ModelCapabilities",
    "ModelDefinition",
    "MockProvider",
    "OfflineProvider",
]
