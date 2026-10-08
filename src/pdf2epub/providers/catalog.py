"""The developer-owned static catalog.

Code-as-data: the catalog is application logic and gets tests here. User
TOML overrides belong to the Phase 6 configuration layer and dynamic model
discovery to v2; neither is a startup dependency. Only ``user_facing=True``
profiles are offered to users; experimental data entries stay hidden until
their profile is exercised against the real endpoint.
"""

from __future__ import annotations

from .models import ModelCapabilities, ModelDefinition
from .profile import CompatOptions, ProviderProfile

PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        provider_id="openai",
        display_name="OpenAI",
        api_style="openai",
        credential_env_var="OPENAI_API_KEY",
        models=(
            ModelDefinition(
                provider_id="openai",
                model_id="gpt-4o",
                display_name="GPT-4o",
                capabilities=ModelCapabilities(
                    image_input=True, structured_output=True, max_context=128000
                ),
            ),
            ModelDefinition(
                provider_id="openai",
                model_id="gpt-4o-mini",
                display_name="GPT-4o mini",
                capabilities=ModelCapabilities(
                    image_input=True, structured_output=True, max_context=128000
                ),
            ),
        ),
    ),
    ProviderProfile(
        provider_id="anthropic",
        display_name="Anthropic",
        api_style="anthropic",
        credential_env_var="ANTHROPIC_API_KEY",
        models=(
            ModelDefinition(
                provider_id="anthropic",
                model_id="claude-sonnet-4-5",
                display_name="Claude Sonnet 4.5",
                # structured_output is the envelope guarantee: this adapter
                # delivers it through prompt discipline, not a native
                # response_format flag (see providers.models).
                capabilities=ModelCapabilities(
                    image_input=True, structured_output=True, max_context=200000
                ),
            ),
        ),
    ),
    # NVIDIA inference endpoints speak the OpenAI chat-completions family
    # but get a dedicated adapter (api_style "nvidia") so their wire
    # behavior is owned by one module. supports_json_mode=False is the
    # conservative default because response_format support varies model
    # by model on NVIDIA endpoints; prompt discipline carries the envelope.
    # Both shipped models are vision-eligible: image_input plus the
    # structured_output guarantee cover the digest and vision routes.
    ProviderProfile(
        provider_id="nvidia",
        display_name="NVIDIA",
        api_style="nvidia",
        credential_env_var="NVIDIA_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
        compat=CompatOptions(
            supports_json_mode=False,
        ),
        models=(
            ModelDefinition(
                provider_id="nvidia",
                model_id="moonshotai/kimi-k3",
                display_name="Kimi K3",
                capabilities=ModelCapabilities(
                    image_input=True, structured_output=True
                ),
            ),
            ModelDefinition(
                provider_id="nvidia",
                model_id="deepseek-ai/deepseek-v4.1-flash",
                display_name="DeepSeek V4.1 Flash",
                capabilities=ModelCapabilities(
                    image_input=True, structured_output=True
                ),
            ),
        ),
        user_facing=True,
    ),
    # Data-only example of an OpenAI-compatible aggregator: a new provider
    # in a known API family is a catalog entry, never a new file. Hidden
    # from users until its profile is exercised against the live endpoint.
    ProviderProfile(
        provider_id="openrouter",
        display_name="OpenRouter",
        api_style="openai",
        credential_env_var="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        allow_generic_key=True,
        compat=CompatOptions(
            extra_headers={
                "HTTP-Referer": "https://github.com/AbhayRjvanshi/pdf2epub-converter",
                "X-Title": "pdf2epub",
            },
            supports_json_mode=False,
            model_id_prefix="openai/",
        ),
        models=(),
        user_facing=False,
    ),
)
