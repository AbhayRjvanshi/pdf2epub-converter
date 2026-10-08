"""Anthropic-style adapter: the Messages API wire contract.

The engine's structured-output envelope is delivered through prompt
discipline (the system prompt demands raw JSON and the engine strips
fences); there is no native response_format flag to pass on this family,
which is why ``supports_json_mode`` is a mechanical compat option and the
model's ``structured_output`` capability is the outcome guarantee.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import LLMClient
from .errors import CredentialError, ProviderUnavailableError, map_sdk_error
from .profile import ProviderProfile

log = logging.getLogger("pdf2epub.providers.anthropic_style")


class AnthropicStyleAdapter:
    """Adapter for every endpoint speaking the Anthropic Messages API."""

    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile
        self.provider_id = profile.provider_id
        self.user_facing = profile.user_facing

    def resolve_models(self) -> list:
        return list(self.profile.models)

    def _import_client(self, credential: str) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            dep = self.profile.client_dependency or "anthropic"
            hint = self.profile.sdk_install_hint() or f"pip install {dep}"
            raise ProviderUnavailableError(
                f"the {dep!r} package is required for provider "
                f"{self.provider_id!r}: {hint}"
            ) from exc
        kwargs: dict[str, Any] = {}
        if self.profile.base_url:
            kwargs["base_url"] = self.profile.base_url
        if self.profile.compat.extra_headers:
            kwargs["default_headers"] = dict(self.profile.compat.extra_headers)
        return anthropic.Anthropic(api_key=credential, **kwargs)

    def validate_credentials(self, credential: str) -> bool:
        """True = the endpoint accepted the key; False = rejected as auth.

        Uses the models route when the installed SDK provides one; older
        SDKs get a 1-token ping, the cheapest probe that still exercises
        authentication. Transport failures raise ProviderUnavailableError.
        """
        client = self._import_client(credential)
        try:
            if hasattr(client, "models") and hasattr(client.models, "list"):
                client.models.list()
            else:
                model = (
                    self.profile.models[0].model_id
                    if self.profile.models
                    else "claude-sonnet-4-5"
                )
                client.messages.create(
                    model=self.profile.compat.with_prefix(model),
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                )
        except Exception as exc:
            normalized = map_sdk_error(exc, secret=credential)
            if isinstance(normalized, CredentialError):
                return False
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

        def llm_client(
            system_prompt: str, payload: str, image_b64: str | None = None
        ) -> str:
            blocks: list[dict[str, Any]] = []
            if image_b64:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    }
                )
            blocks.append({"type": "text", "text": payload})
            try:
                resp = client.messages.create(
                    model=wire_model,
                    max_tokens=8192,
                    temperature=0.0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": blocks}],
                )
            except Exception as exc:
                # `from None`: the SDK traceback could carry the credential
                # in a URL; the redacted normalized message is the diagnosis.
                raise map_sdk_error(exc, secret=credential) from None
            return "".join(
                block.text for block in resp.content if block.type == "text"
            ) or "{}"

        return llm_client
