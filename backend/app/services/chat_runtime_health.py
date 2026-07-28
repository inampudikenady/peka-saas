"""Cached, credential-safe health probe for the independent chat provider."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings, settings


_cache_lock = Lock()
_cache: dict[str, Any] = {"key": None, "checked_at": 0.0, "result": None}


def redacted_base_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        return None


def _base(config: Settings) -> dict[str, Any]:
    return {
        "status": "not_configured",
        "provider": config.peka_chat_provider,
        "model": config.peka_chat_model,
        "base_url": redacted_base_url(config.peka_chat_base_url),
        "connectivity": False,
        "cached_probe": False,
        "streaming_support": config.peka_chat_streaming_enabled,
        "context_window": config.peka_chat_context_window,
        "max_output_tokens": config.peka_chat_max_output_tokens,
        "last_successful_probe": None,
        "reason": "Chat provider is not configured.",
    }


def chat_health(
    config: Settings = settings, *, force: bool = False
) -> dict[str, Any]:
    base = _base(config)
    if config.peka_chat_provider == "disabled":
        return base
    if config.peka_chat_provider == "fake":
        if config.environment.lower() != "test":
            return {
                **base,
                "status": "unavailable",
                "reason": "Test chat provider is forbidden outside tests.",
            }
        return {
            **base,
            "status": "healthy",
            "connectivity": True,
            "reason": None,
        }
    if config.peka_chat_provider != "openai-compatible" or not config.peka_chat_base_url:
        return {
            **base,
            "status": "not_configured",
            "reason": "Chat provider configuration is incomplete.",
        }

    key = (
        config.peka_chat_provider,
        config.peka_chat_base_url,
        config.peka_chat_model,
        bool(config.peka_chat_api_key),
    )
    with _cache_lock:
        age = monotonic() - float(_cache["checked_at"])
        if (
            not force
            and _cache["key"] == key
            and _cache["result"] is not None
            and age < config.peka_chat_health_cache_seconds
        ):
            return {**_cache["result"], "cached_probe": True}

    headers = {"Content-Type": "application/json"}
    if config.peka_chat_api_key:
        headers["Authorization"] = f"Bearer {config.peka_chat_api_key}"
    try:
        response = httpx.post(
            f"{config.peka_chat_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": config.peka_chat_model,
                "messages": [{"role": "user", "content": "Reply only with OK."}],
                "temperature": 0,
                "max_tokens": 2,
                "stream": False,
                "think": False,
                "reasoning_effort": "none",
            },
            timeout=min(config.peka_chat_timeout_seconds, 30),
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError
        now = datetime.now(timezone.utc).isoformat()
        result = {
            **base,
            "status": "healthy",
            "connectivity": True,
            "last_successful_probe": now,
            "reason": None,
        }
    except Exception:
        result = {
            **base,
            "status": "unavailable",
            "reason": "Chat provider generation probe failed.",
        }
    with _cache_lock:
        _cache.update({"key": key, "checked_at": monotonic(), "result": result})
    return result


def clear_chat_health_cache() -> None:
    with _cache_lock:
        _cache.update({"key": None, "checked_at": 0.0, "result": None})
