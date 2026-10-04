"""Deterministic mock provider for tests: no network, repeatable answers.

The default callable returns well-formed ``{"xhtml_pages": [...]}`` matching
the requested page count, which lets application-level tests drive the real
engine end-to-end. Scripted responses (including malformed ones) and a
raise mode let tests simulate every failure class.
"""

from __future__ import annotations

import json
from typing import Iterable

from .base import LLMClient
from .errors import ProviderError
from .models import ModelCapabilities, ModelDefinition

_DEFAULT_MODELS = (
    ModelDefinition(
        provider_id="mock",
        model_id="mock-model",
        display_name="Mock Model",
        capabilities=ModelCapabilities(structured_output=True),
    ),
)


class MockProvider:
    """Programmable provider used by the test suite."""

    provider_id = "mock"

    def __init__(
        self,
        *,
        responses: Iterable[str] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise = raise_error
        self.calls: list[dict] = []  # recorded engine -> provider traffic
        self.models = list(_DEFAULT_MODELS)

    # -- contract -----------------------------------------------------------
    def resolve_models(self) -> list[ModelDefinition]:
        return list(self.models)

    def validate_credentials(self, credential: str) -> bool:
        return credential == "test-key"

    def create_llm_callable(self, model_id: str, credential: str) -> LLMClient:
        if model_id not in {m.model_id for m in self.models}:
            raise ProviderError(f"unknown mock model: {model_id}")

        def client(system_prompt: str, payload: str, image_b64: str | None = None) -> str:
            self.calls.append(
                {
                    "system_prompt": system_prompt,
                    "payload": payload,
                    "image_b64": image_b64,
                }
            )
            if self._raise is not None:
                raise self._raise
            if self._responses:
                return self._responses.pop(0)
            return self._default_response(payload)

        return client

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _default_response(payload: str) -> str:
        """One well-formed XHTML page per requested page."""
        page_nums: list[int] = []
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            pages = parsed.get("pages") or []
            if pages:
                page_nums = [
                    int(p.get("page_num", i + 1)) for i, p in enumerate(pages)
                ]
            elif parsed.get("page_count"):
                page_nums = list(range(1, int(parsed["page_count"]) + 1))
        if not page_nums:
            page_nums = [1]  # vision prompts arrive as plain text
        return json.dumps(
            {"xhtml_pages": [f"<p>Mock page {n}</p>" for n in page_nums]}
        )
