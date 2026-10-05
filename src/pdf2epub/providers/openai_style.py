"""OpenAI-style adapter: one wire contract, many providers.

Speaks the OpenAI chat-completions API family. OpenRouter/DeepSeek-class
services are :class:`~pdf2epub.providers.profile.ProviderProfile` data
over this adapter; a new provider speaking this family is a catalog entry,
never a new file. The SDK is imported lazily inside methods so importing
this module never pulls provider dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import LLMClient
from .errors import (
    CredentialError,
    ModelNotFoundError,
    ProviderUnavailableError,
    map_sdk_error,
)
from .profile import ProviderProfile

log = logging.getLogger("pdf2epub.providers.openai_style")

_INSTALL_HINT = "pip install 'pdf2epub[openai]'"


class OpenAIStyleAdapter:
    """Adapter for every endpoint speaking the OpenAI chat API family."""

    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile
        self.provider_id = profile.provider_id
        self.user_facing = profile.user_facing

    def resolve_models(self) -> list:
        return list(self.profile.models)

    def _import_client(self, credential: str) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderUnavailableError(
                f"the 'openai' package is required for provider "
                f"{self.provider_id!r}: {_INSTALL_HINT}"
            ) from exc
        kwargs: dict[str, Any] = {}
        if self.profile.base_url:
            kwargs["base_url"] = self.profile.base_url
        if self.profile.compat.extra_headers:
            kwargs["default_headers"] = dict(self.profile.compat.extra_headers)
        return OpenAI(api_key=credential, **kwargs)

    def validate_credentials(self, credential: str) -> bool:
        """True = the endpoint accepted the key; False = rejected as auth.

        Transport failures raise ProviderUnavailableError so callers can
        tell "key bad" from "could not ask". A 404 on the models route
        means auth already passed: the endpoint accepted the key, it just
        has no /models to list.
        """
        client = self._import_client(credential)
        try:
            client.models.list()
        except Exception as exc:
            normalized = map_sdk_error(exc, secret=credential)
            if isinstance(normalized, CredentialError):
                return False
            if isinstance(normalized, ModelNotFoundError):
                return True
            raise normalized from None
        return True

    def create_llm_callable(self, model_id: str, credential: str) -> LLMClient:
        if model_id not in {m.model_id for m in self.profile.models}:
            log.warning(
                "provider %r: model %r is not in the static catalog; proceeding",
                self.provider_id,
                model_id,
            )
        client = self._import_client(credential)
        wire_model = self.profile.compat.with_prefix(model_id)
        include_json_mode = self.profile.compat.supports_json_mode

        def llm_client(
            system_prompt: str, payload: str, image_b64: str | None = None
        ) -> str:
            if image_b64:
                content: Any = [
                    {"type": "text", "text": payload},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ]
            else:
                content = payload
            kwargs: dict[str, Any] = {}
            if include_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                resp = client.chat.completions.create(
                    model=wire_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                    temperature=0.0,
                    **kwargs,
                )
            except Exception as exc:
                # `from None`: the SDK traceback could carry the credential
                # in a URL; the redacted normalized message is the diagnosis.
                raise map_sdk_error(exc, secret=credential) from None
            return resp.choices[0].message.content or "{}"

        return llm_client
