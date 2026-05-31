"""Provider registry for summarization backends.

Each provider defines its API endpoint, authentication method, default model,
and wire format. This module is pure data — no network calls.
"""

from __future__ import annotations

from dataclasses import dataclass

# Provider identifiers
PROVIDER_ZAI = "zai"
PROVIDER_OPENROUTER = "openrouter"

VALID_PROVIDERS = [PROVIDER_ZAI, PROVIDER_OPENROUTER]
DEFAULT_PROVIDER = PROVIDER_ZAI


@dataclass(frozen=True)
class ProviderInfo:
    """Immutable configuration for a summarization provider."""

    display_name: str
    env_var: str
    keyring_username: str
    api_url: str
    default_model: str
    api_format: str  # "anthropic" | "openai"


PROVIDERS: dict[str, ProviderInfo] = {
    PROVIDER_ZAI: ProviderInfo(
        display_name="Z.AI",
        env_var="ZAI_API_KEY",
        keyring_username="zai",
        api_url="https://api.z.ai/api/anthropic/v1/messages",
        default_model="GLM-5.1",
        api_format="anthropic",
    ),
    PROVIDER_OPENROUTER: ProviderInfo(
        display_name="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        keyring_username="openrouter",
        api_url="https://openrouter.ai/api/v1/chat/completions",
        default_model="nvidia/nemotron-3-super-120b-a12b:free",
        api_format="openai",
    ),
}
