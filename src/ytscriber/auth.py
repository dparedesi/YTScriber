"""Credential resolution for the OpenRouter API key.

Resolution order (first match wins):

1. Explicit value passed on the command line (``--api-key``)
2. ``OPENROUTER_API_KEY`` environment variable
3. ``.env`` file in the current working directory (via python-dotenv)
4. OS keychain (via keyring: macOS Keychain, Windows Credential Manager,
   libsecret/KWallet on Linux)

All layers are optional. If nothing is found, ``resolve_api_key`` returns
``None`` and callers should degrade gracefully (summarization stays off,
downloads continue).
"""

from __future__ import annotations

from typing import Optional

from ytscriber.logging_config import get_logger

logger = get_logger("auth")

ENV_VAR = "OPENROUTER_API_KEY"
KEYRING_SERVICE = "ytscriber"
KEYRING_USERNAME = "openrouter"

# Lightweight endpoint that returns key info (rate limits, usage). Returns 200
# for a valid key and 401 for an invalid one, without needing a model.
VALIDATE_URL = "https://openrouter.ai/api/v1/key"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

_dotenv_loaded = False


def validate_model(api_key: str, model: str, timeout: float = 20.0) -> tuple[bool, str]:
    """Check whether ``model`` is usable with ``api_key``.

    Sends a minimal chat completion so a missing/unavailable model surfaces as a
    404 here instead of mid-download. Returns a ``(is_valid, message)`` tuple.
    """
    import requests

    try:
        response = requests.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=timeout,
        )
    except requests.RequestException as e:
        return False, f"could not reach OpenRouter ({e})"

    if response.status_code == 200:
        return True, "valid"
    if response.status_code == 404:
        return False, f"model '{model}' not found or not available to your key"
    if response.status_code in (401, 403):
        return False, "invalid or unauthorized API key"
    return False, f"unexpected response (HTTP {response.status_code})"


def validate_api_key(api_key: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Check whether an OpenRouter API key is valid.

    Returns a ``(is_valid, message)`` tuple. Network failures are treated as
    inconclusive (``is_valid`` False) with an explanatory message so callers
    can decide whether to proceed.
    """
    import requests

    try:
        response = requests.get(
            VALIDATE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        return False, f"could not reach OpenRouter ({e})"

    if response.status_code == 200:
        return True, "valid"
    if response.status_code in (401, 403):
        return False, "invalid or unauthorized API key"
    return False, f"unexpected response (HTTP {response.status_code})"


def _load_dotenv_once() -> None:
    """Load a ``.env`` file from the cwd into the environment, once.

    Existing environment variables are never overridden, so the env var
    takes precedence over the ``.env`` file.
    """
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


def get_stored_key() -> Optional[str]:
    """Return the API key from the OS keychain, or ``None``."""
    try:
        import keyring
    except ImportError:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception as e:
        logger.debug(f"Keychain read failed: {e}")
        return None


def set_stored_key(api_key: str) -> bool:
    """Store the API key in the OS keychain. Returns True on success."""
    try:
        import keyring
    except ImportError:
        logger.error("The 'keyring' package is not installed.")
        logger.error("Install it with: pip install keyring")
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)
        return True
    except Exception as e:
        logger.error(f"Could not store key in keychain: {e}")
        return False


def delete_stored_key() -> bool:
    """Delete the API key from the OS keychain. Returns True if removed."""
    try:
        import keyring
        from keyring.errors import PasswordDeleteError
    except ImportError:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        return True
    except PasswordDeleteError:
        return False
    except Exception as e:
        logger.error(f"Could not delete key from keychain: {e}")
        return False


def resolve_api_key(cli_value: Optional[str] = None) -> Optional[str]:
    """Resolve the OpenRouter API key from all configured sources."""
    if cli_value:
        return cli_value
    import os

    _load_dotenv_once()
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return env_value
    return get_stored_key()


def resolve_key_source(cli_value: Optional[str] = None) -> tuple[Optional[str], str]:
    """Resolve the key and report where it came from.

    Returns a ``(key, source)`` tuple. ``source`` is one of
    ``"flag"``, ``"env"``, ``"keychain"`` or ``"none"``.
    """
    if cli_value:
        return cli_value, "flag"
    import os

    _load_dotenv_once()
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return env_value, "env"
    stored = get_stored_key()
    if stored:
        return stored, "keychain"
    return None, "none"


def mask_key(api_key: str) -> str:
    """Return a masked form of the key safe for display."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:5]}...{api_key[-4:]}"
