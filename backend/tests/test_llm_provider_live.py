"""Opt-in checks for the native OpenAI-compatible Ollama runtime."""

import asyncio
import os

import pytest

from app.services.llm_provider import LLMMessage, OpenAICompatibleLLMProvider


pytestmark = pytest.mark.skipif(
    not os.getenv("PEKA_TEST_OLLAMA_URL"),
    reason="Set PEKA_TEST_OLLAMA_URL to run native Ollama integration tests.",
)


def _provider() -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(
        os.environ["PEKA_TEST_OLLAMA_URL"],
        None,
        os.getenv("PEKA_TEST_CHAT_MODEL", "qwen3:8b"),
        embedding_model=os.getenv(
            "PEKA_TEST_EMBEDDING_MODEL", "nomic-embed-text"
        ),
        embedding_dimension=768,
        timeout_seconds=120,
        streaming_enabled=True,
    )


def test_native_ollama_embed_generate_and_stream_without_reasoning():
    async def validate() -> None:
        provider = _provider()
        embedding = await provider.embed(["PEKA native embedding validation"])
        assert len(embedding.vectors) == 1
        assert len(embedding.vectors[0]) == 768

        messages = [
            LLMMessage(
                role="system",
                content="Reply with exactly: Runtime healthy. Do not explain.",
            ),
            LLMMessage(role="user", content="Perform the health reply."),
        ]
        generated = await provider.generate(messages, max_output_tokens=64)
        assert generated.text
        assert "<think>" not in generated.text.lower()
        assert "<analysis>" not in generated.text.lower()

        streamed = ""
        async for chunk in provider.stream(messages, max_output_tokens=64):
            streamed += chunk.text
        assert streamed
        assert "<think>" not in streamed.lower()
        assert "<analysis>" not in streamed.lower()

    asyncio.run(validate())
