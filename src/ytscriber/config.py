"""Configuration handling for ytscriber."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

from ytscriber.paths import get_config_dir

CONFIG_VERSION = 1
DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "defaults": {
        "delay": 60,
        "languages": ["en", "en-US", "en-GB"],
    },
    "summarization": {
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
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
        _merge_config(merged, config)
    merged["version"] = CONFIG_VERSION
    return merged


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
