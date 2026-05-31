"""Tests for credential resolution (auth module)."""

from __future__ import annotations

import ytscriber.auth as auth
from ytscriber.providers import PROVIDER_OPENROUTER, PROVIDER_ZAI


def test_resolve_api_key_prefers_cli_flag(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "env-key")
    assert auth.resolve_api_key("flag-key") == "flag-key"


def test_resolve_api_key_uses_env(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.setenv("ZAI_API_KEY", "env-key")
    assert auth.resolve_api_key() == "env-key"


def test_resolve_api_key_openrouter_env(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert auth.resolve_api_key(provider=PROVIDER_OPENROUTER) == "or-key"


def test_resolve_api_key_falls_back_to_keychain(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(
        auth, "get_stored_key", lambda provider=None: "chain-key"
    )
    assert auth.resolve_api_key() == "chain-key"


def test_resolve_api_key_none(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(auth, "get_stored_key", lambda provider=None: None)
    assert auth.resolve_api_key() is None


def test_resolve_key_source_labels(monkeypatch):
    monkeypatch.setattr(auth, "_dotenv_loaded", True)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(auth, "get_stored_key", lambda provider=None: None)
    key, source = auth.resolve_key_source()
    assert key is None
    assert source == "none"

    assert auth.resolve_key_source("k")[1] == "flag"


def test_mask_key():
    assert auth.mask_key("sk-or-1234567890") == "sk-or...7890"
    assert auth.mask_key("short") == "*****"
    assert auth.mask_key("") == ""


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_validate_api_key_valid_openrouter(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeResponse(200))
    ok, msg = auth.validate_api_key("good-key", provider=PROVIDER_OPENROUTER)
    assert ok is True
    assert msg == "valid"


def test_validate_api_key_unauthorized_openrouter(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeResponse(401))
    ok, msg = auth.validate_api_key("bad-key", provider=PROVIDER_OPENROUTER)
    assert ok is False
    assert "invalid" in msg


def test_validate_api_key_network_error_openrouter(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.RequestException("no network")

    monkeypatch.setattr("requests.get", boom)
    ok, msg = auth.validate_api_key("any-key", provider=PROVIDER_OPENROUTER)
    assert ok is False
    assert "could not reach" in msg


def test_validate_api_key_valid_zai(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(200))
    ok, msg = auth.validate_api_key("good-key", provider=PROVIDER_ZAI)
    assert ok is True
    assert msg == "valid"


def test_validate_api_key_unauthorized_zai(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(401))
    ok, msg = auth.validate_api_key("bad-key", provider=PROVIDER_ZAI)
    assert ok is False
    assert "unauthorized" in msg


def test_validate_model_valid(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(200))
    ok, msg = auth.validate_model("good-key", "vendor/model")
    assert ok is True
    assert msg == "valid"


def test_validate_model_not_found(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(404))
    ok, msg = auth.validate_model("good-key", "vendor/missing")
    assert ok is False
    assert "not found" in msg


def test_validate_model_unauthorized(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(401))
    ok, msg = auth.validate_model("bad-key", "vendor/model")
    assert ok is False
    assert "unauthorized" in msg
