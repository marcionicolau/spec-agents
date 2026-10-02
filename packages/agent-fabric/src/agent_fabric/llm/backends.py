"""LLM backends. Everything talks to the LiteLLM proxy through its OpenAI-compatible API.

The proxy owns model routing (aliases -> Ollama models, fallbacks, retries,
timeouts); this code only knows *aliases* such as ``local-planner``.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..errors import DependencyError, ErrorDetail

type Message = dict[str, str]


class LLMSettings(BaseModel):
    base_url: str = Field(default_factory=lambda: os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1"))
    api_key: str = Field(default_factory=lambda: os.getenv("LITELLM_API_KEY", "sk-local-dev"))
    planner_model: str = "local-planner"
    interpreter_model: str = "local-writer"
    repair_model: str = "local-fast"
    temperature: float = Field(0.1, ge=0, le=2)
    timeout_s: float = 180.0
    max_correction_attempts: int = Field(3, ge=1, le=6)
    json_mode: bool = True
    pydantic_ai_output_mode: str = Field("prompted", pattern="^(prompted|tool|native)$")


class LLMBackend(Protocol):
    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Return the model's answer text for a chat ``messages`` list.

        ``model`` is a LiteLLM alias (backend default when ``None``), ``json_mode`` asks for a JSON object and ``temperature`` overrides the
        backend default. Failures are raised as `DependencyError`.
        """
        ...


class AsyncLLMBackend(Protocol):
    """Async twin of `LLMBackend`; same arguments and the same `DependencyError` failures."""

    async def acomplete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Return the model's answer text for a chat ``messages`` list (see `LLMBackend.complete`)."""
        ...


class StreamingLLMBackend(Protocol):
    """Backend that can stream an answer as text deltas."""

    def astream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Yield the answer as text deltas; their concatenation equals what ``complete`` would return."""
        ...


class SyncToAsyncBackend:
    """Adapts any sync `LLMBackend` to `AsyncLLMBackend` by running ``complete`` in a worker thread.

    ``astream`` yields the whole answer as a single delta, so streaming consumers work with any backend.
    """

    def __init__(self, inner: LLMBackend) -> None:
        self.inner = inner

    async def acomplete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Run the wrapped backend's ``complete`` in a worker thread and return its text."""
        return await asyncio.to_thread(
            self.inner.complete, messages, model=model, json_mode=json_mode, temperature=temperature
        )

    async def astream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Yield the complete answer as one delta."""
        text = await self.acomplete(messages, model=model, json_mode=json_mode, temperature=temperature)
        if text:
            yield text


class LiteLLMProxyBackend:
    """Minimal OpenAI-compatible client (stdlib only) for the LiteLLM proxy."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.s = settings or LLMSettings()

    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """POST a chat completion to the LiteLLM proxy (OpenAI-compatible ``/chat/completions``) and return the message text.

        ``model`` defaults to the planner alias of the settings. Raises `DependencyError` with a hint for an HTTP error (``http_error``), an unreachable
        proxy (``connection_error``) or an unexpected response shape (``bad_response``).
        """
        req = self._request(messages, model, json_mode, temperature, stream=False)
        try:
            with urllib.request.urlopen(req, timeout=self.s.timeout_s) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise self._dependency_error(exc) from exc
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise DependencyError(
                "Unexpected response shape from proxy", [ErrorDetail(type="bad_response", msg=str(payload)[:300])]
            ) from exc

    async def acomplete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Async `complete`: the blocking request runs in a worker thread so other coroutines keep running."""
        return await asyncio.to_thread(
            self.complete, messages, model=model, json_mode=json_mode, temperature=temperature
        )

    async def astream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion (server-sent events) and yield the text deltas as they arrive.

        Failures are raised as `DependencyError` exactly like `complete`; a malformed event is ``bad_response``.
        """
        req = self._request(messages, model, json_mode, temperature, stream=True)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

        def pump() -> None:
            try:
                with urllib.request.urlopen(req, timeout=self.s.timeout_s) as resp:
                    for raw in resp:
                        line = raw.decode(errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                        except (KeyError, IndexError, TypeError, ValueError) as exc:
                            raise DependencyError(
                                "Unexpected stream event from proxy",
                                [ErrorDetail(type="bad_response", msg=data[:300])],
                            ) from exc
                        if delta:
                            loop.call_soon_threadsafe(queue.put_nowait, delta)
            except DependencyError as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                loop.call_soon_threadsafe(queue.put_nowait, self._dependency_error(exc))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.get_running_loop().run_in_executor(None, pump)
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            await asyncio.shield(task)

    # ------------------------------------------------------------------ helpers
    def _request(
        self, messages: list[Message], model: str | None, json_mode: bool, temperature: float | None, *, stream: bool
    ) -> urllib.request.Request:
        body: dict[str, Any] = {
            "model": model or self.s.planner_model,
            "messages": messages,
            "temperature": self.s.temperature if temperature is None else temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if stream:
            body["stream"] = True
        return urllib.request.Request(
            self.s.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.s.api_key}"},
            method="POST",
        )

    def _dependency_error(self, exc: Exception) -> DependencyError:
        if isinstance(exc, urllib.error.HTTPError):
            detail = exc.read().decode(errors="replace")[:500]
            return DependencyError(
                f"LiteLLM proxy returned HTTP {exc.code}",
                [
                    ErrorDetail(
                        type="http_error",
                        msg=detail,
                        hint="check model alias in config/litellm_config.yaml and that Ollama has pulled it",
                    )
                ],
            )
        return DependencyError(
            "LiteLLM proxy is unreachable",
            [
                ErrorDetail(
                    type="connection_error",
                    msg=str(exc)[:300],
                    hint=f"start it: litellm --config config/litellm_config.yaml (expected at {self.s.base_url})",
                )
            ],
        )


class ScriptedBackend:
    """Deterministic backend for tests/demos: replays responses (strings or callables) in order."""

    def __init__(self, responses: Iterable[str | Callable[[list[Message]], str]]) -> None:
        self.responses: deque[str | Callable[[list[Message]], str]] = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Return the next scripted response; a callable response receives the messages.

        Every call is recorded in ``calls`` (messages, model, json_mode). Raises ``AssertionError`` when the script is exhausted. For offline tests and demos.
        """
        self.calls.append({"messages": [dict(m) for m in messages], "model": model, "json_mode": json_mode})
        if not self.responses:
            raise AssertionError("ScriptedBackend ran out of responses")
        nxt = self.responses.popleft()
        return nxt if isinstance(nxt, str) else nxt(messages)

    async def acomplete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Async `complete`: same script, same recorded ``calls``; runs inline (deterministic, no thread)."""
        return self.complete(messages, model=model, json_mode=json_mode, temperature=temperature)

    async def astream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        chunk_size: int = 16,
    ) -> AsyncIterator[str]:
        """Yield the next scripted response in ``chunk_size``-character deltas."""
        text = self.complete(messages, model=model, json_mode=json_mode, temperature=temperature)
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]


__all__ = [
    "AsyncLLMBackend",
    "LLMBackend",
    "LLMSettings",
    "LiteLLMProxyBackend",
    "Message",
    "ScriptedBackend",
    "StreamingLLMBackend",
    "SyncToAsyncBackend",
]
