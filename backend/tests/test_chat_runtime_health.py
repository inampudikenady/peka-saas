from app.core.config import Settings
from app.services.chat_runtime_health import (
    chat_health,
    clear_chat_health_cache,
    redacted_base_url,
)


def test_chat_not_configured_is_independent():
    result = chat_health(Settings(debug=False, peka_chat_provider="disabled"))
    assert result["status"] == "not_configured"
    assert result["streaming_support"] is True


def test_chat_probe_is_cached_and_redacts_credentials(monkeypatch):
    calls = 0

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    def post(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["headers"]["Authorization"] == "Bearer private-secret"
        return Response()

    monkeypatch.setattr("httpx.post", post)
    clear_chat_health_cache()
    config = Settings(
        debug=False,
        peka_chat_provider="openai-compatible",
        peka_chat_base_url="http://user:password@localhost:11434/v1?token=private",
        peka_chat_api_key="private-secret",
        peka_chat_model="qwen3:8b",
    )
    first = chat_health(config)
    second = chat_health(config)
    assert first["status"] == "healthy"
    assert second["cached_probe"] is True
    assert calls == 1
    assert "password" not in str(second)
    assert "private" not in str(second)


def test_chat_unavailable_has_only_safe_reason(monkeypatch):
    monkeypatch.setattr(
        "httpx.post", lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("raw provider payload")
        )
    )
    clear_chat_health_cache()
    result = chat_health(
        Settings(
            debug=False,
            peka_chat_provider="openai-compatible",
            peka_chat_base_url="http://localhost:11434/v1",
        ),
        force=True,
    )
    assert result["status"] == "unavailable"
    assert "raw provider payload" not in str(result)


def test_redacted_base_url_removes_userinfo_and_query():
    assert redacted_base_url(
        "https://user:secret@example.com:8443/v1?api_key=secret"
    ) == "https://example.com:8443/v1"
