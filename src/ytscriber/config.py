"""Configuration handling for ytscriber."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

from ytscriber.logging_config import get_logger
from ytscriber.paths import get_config_dir
from ytscriber.providers import DEFAULT_PROVIDER, PROVIDER_ZAI, VALID_PROVIDERS

logger = get_logger("config")

CONFIG_VERSION = 2
DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "defaults": {
        "delay": 60,
        "languages": ["en", "en-US", "en-GB"],
    },
    "summarization": {
        "provider": DEFAULT_PROVIDER,
        "model": "GLM-5.1",
        "max_words": 500,
    },
}


def get_config_path() -> Path:
    """Return the configuration file path."""
    return get_config_dir() / "config.yaml"


def default_config() -> dict[str, Any]:
    """Return a deep copy of the default config."""
    return deepcopy(DEFAULT_CONFIG)


def read_config() -> Optional[dict[str, Any]]:
    """Read raw config without merging defaults."""
    config_path = get_config_path()
    if not config_path.exists():
        return None
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_config(base[key], value)
        else:
            base[key] = value
    return base


def normalize_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Merge defaults into config and ensure version is current."""
    merged = default_config()
    if config:
        # Migrate v1 configs that lack a provider key
        _migrate_provider(config)
        # Validate provider value
        _validate_provider(config)
        _merge_config(merged, config)
    merged["version"] = CONFIG_VERSION
    return merged


def _migrate_provider(config: dict[str, Any]) -> None:
    """Add provider key to v1 configs by inferring from model name."""
    summ = config.get("summarization")
    if not isinstance(summ, dict):
        return
    if "provider" in summ:
        return
    model = summ.get("model", "")
    # OpenRouter models use "vendor/model" format (e.g. "nvidia/nemotron-...")
    if "/" in str(model):
        summ["provider"] = "openrouter"
    else:
        summ["provider"] = PROVIDER_ZAI


def _validate_provider(config: dict[str, Any]) -> None:
    """Warn and fix unknown provider values."""
    summ = config.get("summarization")
    if not isinstance(summ, dict):
        return
    provider = summ.get("provider")
    if provider and provider not in VALID_PROVIDERS:
        logger.warning(
            f"Unknown provider '{provider}' in config, "
            f"falling back to {DEFAULT_PROVIDER}"
        )
        summ["provider"] = DEFAULT_PROVIDER


def load_config() -> dict[str, Any]:
    """Load config and merge with defaults."""
    return normalize_config(read_config())


def save_config(config: dict[str, Any]) -> None:
    """Write config to disk."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )


def parse_config_value(value: str) -> Any:
    """Parse a config value from CLI input."""
    try:
        return yaml.safe_load(value)
    except Exception:
        return value


def set_config_value(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set a nested config value using dotted keys."""
    parts = [part for part in dotted_key.split(".") if part]
    if not parts:
        return
    cursor = config
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value
