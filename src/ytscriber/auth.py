"""Credential resolution for summarization providers.

Supports two backends:

- **Z.AI** (default) — Anthropic-compatible Messages API at ``api.z.ai``
- **OpenRouter** — OpenAI-compatible chat completions at ``openrouter.ai``

Resolution order (first match wins):

1. Explicit value passed on the command line (``--api-key``)
2. Provider-specific environment variable (``ZAI_API_KEY`` or ``OPENROUTER_API_KEY``)
3. ``.env`` file in the current working directory (via python-dotenv)
4. OS keychain (via keyring: macOS Keychain, Windows Credential Manager,
   libsecret/KWallet on Linux)

All layers are optional. If nothing is found, ``resolve_api_key`` returns
``None`` and callers should degrade gracefully (summarization stays off,
downloads continue).
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from ytscriber.logging_config import get_logger
from ytscriber.providers import (
    DEFAULT_PROVIDER,
    PROVIDER_OPENROUTER,
    PROVIDER_ZAI,
    PROVIDERS,
    VALID_PROVIDERS,
)

logger = get_logger("auth")

KEYRING_SERVICE = "ytscriber"

_dotenv_loaded = False


# ---------------------------------------------------------------------------
# Shared provider API call helpers (used by both validation and summarizer)
# ---------------------------------------------------------------------------


def call_provider_api(
    provider: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = 1,
    timeout: float = 20.0,
    extra_body: Optional[dict[str, Any]] = None,
) -> requests.Response:
    """Send a chat-style request to the given provider.

    This is the single point of truth for provider-specific headers, body
    format, and endpoint URL.  Used by both ``validate_model`` and the
    summarizer.
    """
    pconf = PROVIDERS[provider]

    if pconf.api_format == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    else:  # openai
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        if extra_body:
            body.update(extra_body)

    return requests.post(pconf.api_url, headers=headers, json=body, timeout=timeout)


def extract_response_text(data: dict[str, Any], provider: str) -> str:
    """Extract the assistant text from a provider-specific response JSON."""
    if provider == PROVIDER_ZAI:
        return data["content"][0]["text"].strip()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_api_key(
    api_key: str,
    provider: Optional[str] = None,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Check whether an API key is valid for the given provider.

    Returns a ``(is_valid, message)`` tuple.  Network failures are treated
    as inconclusive (``is_valid`` False) with an explanatory message.
    """
    provider = provider or DEFAULT_PROVIDER
    pconf = PROVIDERS[provider]

    if provider == PROVIDER_OPENROUTER:
        # OpenRouter has a dedicated lightweight key-check endpoint.
        try:
            response = requests.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
        except requests.RequestException as e:
            return False, f"could not reach {pconf.display_name} ({e})"

        if response.status_code == 200:
            return True, "valid"
        if response.status_code in (401, 403):
            return False, "invalid or unauthorized API key"
        return False, f"unexpected response (HTTP {response.status_code})"

    # Z.AI and others — validate by sending a minimal chat request.
    return validate_model(api_key, pconf.default_model, provider=provider, timeout=timeout)


def validate_model(
    api_key: str,
    model: str,
    provider: Optional[str] = None,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """Check whether *model* is usable with *api_key* on *provider*.

    Sends a minimal completion so a missing/unavailable model surfaces as a
    404 here instead of mid-download.  Returns a ``(is_valid, message)`` tuple.
    """
    provider = provider or DEFAULT_PROVIDER
    pconf = PROVIDERS[provider]

    try:
        response = call_provider_api(
            provider, api_key, model, "ping", max_tokens=1, timeout=timeout
        )
    except requests.RequestException as e:
        return False, f"could not reach {pconf.display_name} ({e})"

    if response.status_code == 200:
        return True, "valid"
    if response.status_code == 404:
        return False, f"model '{model}' not found or not available to your key"
    if response.status_code in (401, 403):
        return False, "invalid or unauthorized API key"
    return False, f"unexpected response (HTTP {response.status_code})"


# ---------------------------------------------------------------------------
# dotenv loader
# ---------------------------------------------------------------------------


def _load_dotenv_once() -> None:
    """Load a ``.env`` file from the cwd into the environment, once."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    try:
        load_dotenv(override=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------


def get_stored_key(provider: Optional[str] = None) -> Optional[str]:
    """Return the API key from the OS keychain, or ``None``."""
    provider = provider or DEFAULT_PROVIDER
    username = PROVIDERS[provider].keyring_username
    try:
        import keyring
    except ImportError:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, username)
    except Exception as e:
        logger.debug(f"Keychain read failed: {e}")
        return None


def set_stored_key(api_key: str, provider: Optional[str] = None) -> bool:
    """Store the API key in the OS keychain.  Returns True on success."""
    provider = provider or DEFAULT_PROVIDER
    username = PROVIDERS[provider].keyring_username
    try:
        import keyring
    except ImportError:
        logger.error("The 'keyring' package is not installed.")
        logger.error("Install it with: pip install keyring")
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, username, api_key)
        return True
    except Exception as e:
        logger.error(f"Could not store key in keychain: {e}")
        return False


def delete_stored_key(provider: Optional[str] = None) -> bool:
    """Delete the API key from the OS keychain.  Returns True if removed."""
    provider = provider or DEFAULT_PROVIDER
    username = PROVIDERS[provider].keyring_username
    try:
        import keyring
        from keyring.errors import PasswordDeleteError
    except ImportError:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, username)
        return True
    except PasswordDeleteError:
        return False
    except Exception as e:
        logger.error(f"Could not delete key from keychain: {e}")
        return False


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------


def resolve_api_key(
    cli_value: Optional[str] = None,
    provider: Optional[str] = None,
) -> Optional[str]:
    """Resolve the API key for *provider* from all configured sources."""
    provider = provider or DEFAULT_PROVIDER
    if cli_value:
        return cli_value
    import os

    _load_dotenv_once()
    env_value = os.environ.get(PROVIDERS[provider].env_var)
    if env_value:
        return env_value
    return get_stored_key(provider)


def resolve_key_source(
    cli_value: Optional[str] = None,
    provider: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Resolve the key and report where it came from.

    Returns a ``(key, source)`` tuple.  ``source`` is one of
    ``"flag"``, ``"env"``, ``"keychain"`` or ``"none"``.
    """
    provider = provider or DEFAULT_PROVIDER
    if cli_value:
        return cli_value, "flag"
    import os

    _load_dotenv_once()
    env_value = os.environ.get(PROVIDERS[provider].env_var)
    if env_value:
        return env_value, "env"
    stored = get_stored_key(provider)
    if stored:
        return stored, "keychain"
    return None, "none"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def mask_key(api_key: str) -> str:
    """Return a masked form of the key safe for display."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:5]}...{api_key[-4:]}"
