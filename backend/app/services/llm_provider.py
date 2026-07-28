"""Replaceable async LLM provider boundary for embeddings and final answers."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import httpx


@dataclass(frozen=True)
class ProviderCapabilities:
    embeddings: bool
    generation: bool
    streaming: bool
    structured_output: bool = False
    reasoning_control: bool = True


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    output_tokens: int | None = None


@dataclass(frozen=True)
class GenerationChunk:
    text: str


class LLMProvider(Protocol):
    name: str
    model: str

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def embed(
        self, inputs: list[str], *, model: str | None = None
    ) -> EmbeddingResult: ...

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> GenerationResult: ...

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[GenerationChunk]: ...


class LLMProviderError(RuntimeError):
    code = "AI_GENERATION_FAILED"


class LLMProviderNotConfigured(LLMProviderError):
    code = "CHAT_PROVIDER_NOT_CONFIGURED"


class LLMProviderUnavailable(LLMProviderError):
    code = "CHAT_PROVIDER_UNAVAILABLE"


class LLMProviderTimeout(LLMProviderError):
    code = "CHAT_PROVIDER_TIMEOUT"


class LLMProviderRateLimited(LLMProviderError):
    code = "CHAT_PROVIDER_RATE_LIMITED"


class LLMProviderInvalidResponse(LLMProviderError):
    code = "CHAT_PROVIDER_INVALID_RESPONSE"


class LLMContextExceeded(LLMProviderError):
    code = "CONTEXT_LIMIT_EXCEEDED"


class LLMCapabilityUnsupported(LLMProviderError):
    code = "AI_GENERATION_FAILED"


_REASONING_BLOCK = re.compile(
    r"<(?:think|thinking|analysis|reasoning)>.*?</(?:think|thinking|analysis|reasoning)>",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_REASONING = re.compile(
    r"<(?:think|thinking|analysis|reasoning)>.*$",
    re.IGNORECASE | re.DOTALL,
)


def suppress_reasoning(text: str) -> str:
    """Remove provider reasoning tags as defense in depth after channel filtering."""
    text = _REASONING_BLOCK.sub("", text)
    return _UNCLOSED_REASONING.sub("", text).strip()


class _StreamingReasoningFilter:
    _open = re.compile(r"<(?:think|thinking|analysis|reasoning)>", re.IGNORECASE)
    _close = re.compile(r"</(?:think|thinking|analysis|reasoning)>", re.IGNORECASE)

    def __init__(self) -> None:
        self.buffer = ""
        self.inside = False

    def feed(self, value: str, final: bool = False) -> list[str]:
        self.buffer += value
        output: list[str] = []
        while self.buffer:
            pattern = self._close if self.inside else self._open
            match = pattern.search(self.buffer)
            if match:
                if not self.inside and match.start():
                    output.append(self.buffer[:match.start()])
                self.buffer = self.buffer[match.end():]
                self.inside = not self.inside
                continue
            if self.inside:
                if final:
                    self.buffer = ""
                elif len(self.buffer) > 32:
                    self.buffer = self.buffer[-32:]
                break
            if final:
                output.append(self.buffer)
                self.buffer = ""
            else:
                possible_tag = self.buffer.rfind("<")
                if possible_tag < 0:
                    output.append(self.buffer)
                    self.buffer = ""
                elif possible_tag > 0:
                    output.append(self.buffer[:possible_tag])
                    self.buffer = self.buffer[possible_tag:]
                break
        return [item for item in output if item]


class OpenAICompatibleLLMProvider:
    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        chat_model: str,
        *,
        embedding_model: str,
        embedding_dimension: int,
        timeout_seconds: float,
        streaming_enabled: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = chat_model
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.timeout_seconds = timeout_seconds
        self.streaming_enabled = streaming_enabled

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            embeddings=True,
            generation=True,
            streaming=self.streaming_enabled,
        )

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(
        self,
        messages: list[LLMMessage],
        model: str | None,
        temperature: float | None,
        max_output_tokens: int | None,
        *,
        stream: bool,
    ) -> dict[str, object]:
        return {
            "model": model or self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "stream": stream,
            # Supported by native Ollama for reasoning-capable models and safely
            # ignored by compatible providers that allow extra request fields.
            "think": False,
            # Ollama's OpenAI-compatible endpoint maps this field to its native
            # thinking control; `think` is retained for other compatible APIs.
            "reasoning_effort": "none",
        }

    @staticmethod
    def _map_status(response: httpx.Response) -> None:
        if response.status_code == 429:
            raise LLMProviderRateLimited("The chat provider rate limit was reached.")
        if response.status_code in {408, 504}:
            raise LLMProviderTimeout("The chat provider timed out.")
        if response.status_code in {400, 413}:
            body = response.text.lower()[:500]
            if "context" in body or "token" in body:
                raise LLMContextExceeded("The provider context limit was exceeded.")
            raise LLMProviderInvalidResponse("The chat provider rejected the request.")
        if response.status_code in {401, 403, 404}:
            raise LLMProviderUnavailable("The configured chat provider is unavailable.")
        if response.status_code >= 500:
            raise LLMProviderUnavailable("The chat provider is temporarily unavailable.")
        if not response.is_success:
            raise LLMProviderInvalidResponse("The chat provider returned an invalid response.")

    async def _post_json(
        self, path: str, payload: dict[str, object]
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self.timeout_seconds)
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.base_url}{path}",
                        headers=self._headers,
                        json=payload,
                    )
                if response.status_code >= 500 and attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
                self._map_status(response)
                value = response.json()
                if not isinstance(value, dict):
                    raise ValueError
                return cast(dict[str, Any], value)
            except LLMProviderError:
                raise
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
                raise LLMProviderTimeout("The chat provider timed out.") from exc
            except httpx.HTTPError as exc:
                if attempt == 0:
                    await asyncio.sleep(0.1)
                    continue
                raise LLMProviderUnavailable(
                    "The chat provider is temporarily unavailable."
                ) from exc
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise LLMProviderInvalidResponse(
                    "The chat provider returned an invalid response."
                ) from exc
        raise LLMProviderUnavailable("The chat provider is temporarily unavailable.")

    async def embed(
        self, inputs: list[str], *, model: str | None = None
    ) -> EmbeddingResult:
        data = await self._post_json(
            "/embeddings",
            {"model": model or self.embedding_model, "input": inputs},
        )
        try:
            vectors = [item["embedding"] for item in data["data"]]
            if len(vectors) != len(inputs) or any(
                len(vector) != self.embedding_dimension for vector in vectors
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMProviderInvalidResponse(
                "The embedding provider returned an invalid response."
            ) from exc
        return EmbeddingResult(vectors=vectors, model=model or self.embedding_model)

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> GenerationResult:
        data = await self._post_json(
            "/chat/completions",
            self._payload(
                messages,
                model,
                temperature,
                max_output_tokens,
                stream=False,
            ),
        )
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
            if not isinstance(text, str):
                raise ValueError
            if choice.get("finish_reason") == "length":
                raise LLMProviderInvalidResponse(
                    "The chat provider truncated its response."
                )
            usage = data.get("usage") or {}
            output_tokens = usage.get("completion_tokens")
        except LLMProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderInvalidResponse(
                "The chat provider returned an invalid response."
            ) from exc
        return GenerationResult(
            text=suppress_reasoning(text),
            model=str(data.get("model") or model or self.model),
            output_tokens=int(output_tokens) if isinstance(output_tokens, int) else None,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[GenerationChunk]:
        if not self.streaming_enabled:
            raise LLMCapabilityUnsupported("Streaming is not enabled.")
        timeout = httpx.Timeout(self.timeout_seconds)
        reasoning_filter = _StreamingReasoningFilter()
        finish_reason: str | None = None
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers,
                    json=self._payload(
                        messages,
                        model,
                        temperature,
                        max_output_tokens,
                        stream=True,
                    ),
                ) as response:
                    self._map_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            payload = json.loads(data)
                            delta = payload["choices"][0]["delta"]
                            finish_reason = payload["choices"][0].get("finish_reason")
                            # Deliberately ignore reasoning/reasoning_content fields.
                            content = delta.get("content") or ""
                            if not isinstance(content, str):
                                raise ValueError
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
                            raise LLMProviderInvalidResponse(
                                "The chat provider returned an invalid stream."
                            ) from exc
                        for final_text in reasoning_filter.feed(content):
                            yield GenerationChunk(final_text)
            for final_text in reasoning_filter.feed("", final=True):
                yield GenerationChunk(final_text)
            if finish_reason == "length":
                raise LLMProviderInvalidResponse(
                    "The chat provider truncated its response."
                )
        except LLMProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeout("The chat provider timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderUnavailable(
                "The chat provider is temporarily unavailable."
            ) from exc


class DisabledLLMProvider:
    name = "disabled"
    model = "not-configured"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(False, False, False)

    async def embed(
        self, inputs: list[str], *, model: str | None = None
    ) -> EmbeddingResult:
        raise LLMProviderNotConfigured("The chat provider is not configured.")

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> GenerationResult:
        raise LLMProviderNotConfigured("The chat provider is not configured.")

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[GenerationChunk]:
        raise LLMProviderNotConfigured("The chat provider is not configured.")
        yield GenerationChunk("")


class DeterministicFakeLLMProvider:
    """Test-only provider with no environment-dependent behavior."""

    name = "deterministic-fake"
    model = "test-answer-model"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(True, True, True)

    async def embed(
        self, inputs: list[str], *, model: str | None = None
    ) -> EmbeddingResult:
        from app.services.embedding_provider import DeterministicFakeEmbeddingProvider

        return EmbeddingResult(
            vectors=DeterministicFakeEmbeddingProvider(16).embed(inputs),
            model="sha256-test-only",
        )

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> GenerationResult:
        return GenerationResult(
            text="The available evidence supports this test answer. [C1]",
            model=self.model,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[GenerationChunk]:
        for value in ("The available evidence ", "supports this test answer. [C1]"):
            yield GenerationChunk(value)
