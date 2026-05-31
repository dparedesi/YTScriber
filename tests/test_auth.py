"""Tests for credential resolution (auth module)."""

from __future__ import annotations

import ytscriber.auth as auth


def test_resolve_api_key_prefers_cli_flag(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    assert auth.resolve_api_key("flag-key") == "flag-key"


def test_resolve_api_key_uses_env(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    assert auth.resolve_api_key() == "env-key"


def test_resolve_api_key_falls_back_to_keychain(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(auth, "get_stored_key", lambda: "chain-key")
    assert auth.resolve_api_key() == "chain-key"


def test_resolve_api_key_none(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(auth, "get_stored_key", lambda: None)
    assert auth.resolve_api_key() is None


def test_resolve_key_source_labels(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(auth, "get_stored_key", lambda: None)
    key, source = auth.resolve_key_source()
    assert key is None
    assert source == "none"

    assert auth.resolve_key_source("k")[1] == "flag"


def test_mask_key():
    assert auth.mask_key("sk-or-1234567890") == "sk-or...7890"
    assert auth.mask_key("short") == "*****"
    assert auth.mask_key("") == ""
