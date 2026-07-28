import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.services.llm_provider import (
    LLMContextExceeded,
    LLMMessage,
    LLMProviderInvalidResponse,
    LLMProviderRateLimited,
    OpenAICompatibleLLMProvider,
    _StreamingReasoningFilter,
    suppress_reasoning,
)
from app.services.provider_factory import chat_provider


def provider() -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(
        "http://localhost:11434/v1",
        "never-print-this",
        "qwen3:8b",
        embedding_model="nomic-embed-text",
        embedding_dimension=768,
        timeout_seconds=10,
        streaming_enabled=True,
    )


def test_fake_chat_provider_is_forbidden_outside_tests():
    with pytest.raises(Exception, match="restricted"):
        chat_provider(Settings(debug=False, environment="development", peka_chat_provider="fake"))


def test_reasoning_suppression_removes_complete_and_unclosed_blocks():
    assert suppress_reasoning("<think>private reasoning</think>Final [C1]") == "Final [C1]"
    assert suppress_reasoning("Final [C1]<analysis>never expose") == "Final [C1]"


def test_streaming_reasoning_filter_handles_split_tags():
    filter_ = _StreamingReasoningFilter()
    output: list[str] = []
    for value in ("<thi", "nk>secret", " chain</th", "ink>Final ", "[C1]"):
        output.extend(filter_.feed(value))
    output.extend(filter_.feed("", final=True))
    assert "".join(output) == "Final [C1]"
    assert "secret" not in "".join(output)


def test_openai_generation_request_disables_reasoning(monkeypatch):
    captured = {}

    async def fake_post(path, payload):
        captured.update({"path": path, "payload": payload})
        return {
            "model": "qwen3:8b",
            "choices": [{"message": {"content": "<think>hidden</think>Answer [C1]"}}],
        }

    value = provider()
    monkeypatch.setattr(value, "_post_json", fake_post)
    result = asyncio.run(
        value.generate(
            [LLMMessage(role="system", content="policy"), LLMMessage(role="user", content="question")],
            max_output_tokens=100,
        )
    )
    assert captured["path"] == "/chat/completions"
    assert captured["payload"]["think"] is False
    assert captured["payload"]["reasoning_effort"] == "none"
    assert result.text == "Answer [C1]"
    assert "never-print-this" not in repr(captured)


def test_truncated_generation_is_rejected(monkeypatch):
    async def fake_post(path, payload):
        return {
            "choices": [
                {
                    "message": {"content": "Incomplete answer [C1]"},
                    "finish_reason": "length",
                }
            ]
        }

    value = provider()
    monkeypatch.setattr(value, "_post_json", fake_post)
    with pytest.raises(LLMProviderInvalidResponse):
        asyncio.run(
            value.generate([LLMMessage(role="user", content="question")])
        )


def test_provider_status_mapping_is_safe():
    rate_limited = httpx.Response(429, request=httpx.Request("POST", "http://provider"))
    with pytest.raises(LLMProviderRateLimited):
        provider()._map_status(rate_limited)
    context = httpx.Response(
        400,
        text="context length exceeded private payload",
        request=httpx.Request("POST", "http://provider"),
    )
    with pytest.raises(LLMContextExceeded):
        provider()._map_status(context)
    invalid = httpx.Response(422, request=httpx.Request("POST", "http://provider"))
    with pytest.raises(LLMProviderInvalidResponse):
        provider()._map_status(invalid)
