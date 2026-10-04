"""The explicit-offline provider (``--provider none``).

Offline is not a fake provider: it is the application's uniform handle for
"no LLM at all". The engine expresses offline mode as ``llm_adapter=None``,
so the application maps this adapter to ``None`` on the engine seam rather
than fabricating a callable; ``create_llm_callable`` therefore raises if
misused. Offline needs no credential (decision #5), offers no models, and
model validation is skipped for it (decision #10).
"""

from __future__ import annotations

from .base import LLMClient
from .errors import ProviderError
from .models import ModelDefinition


class OfflineProvider:
    provider_id = "none"

    def resolve_models(self) -> list[ModelDefinition]:
        return []

    def validate_credentials(self, credential: str) -> bool:
        return True  # nothing to verify

    def create_llm_callable(self, model_id: str, credential: str) -> LLMClient:
        raise ProviderError(
            "offline provider never creates an LLM callable; "
            "pass llm_adapter=None to the engine instead"
        )
