"""LLM backends. Everything talks to the LiteLLM proxy through its OpenAI-compatible API.

The proxy owns model routing (aliases -> Ollama models, fallbacks, retries,
timeouts); this code only knows *aliases* such as ``local-planner``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Iterable
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
    ) -> str: ...


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
        body: dict[str, Any] = {
            "model": model or self.s.planner_model,
            "messages": messages,
            "temperature": self.s.temperature if temperature is None else temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            self.s.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.s.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.s.timeout_s) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise DependencyError(
                f"LiteLLM proxy returned HTTP {exc.code}",
                [
                    ErrorDetail(
                        type="http_error",
                        msg=detail,
                        hint="check model alias in config/litellm_config.yaml and that Ollama has pulled it",
                    )
                ],
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DependencyError(
                "LiteLLM proxy is unreachable",
                [
                    ErrorDetail(
                        type="connection_error",
                        msg=str(exc)[:300],
                        hint=f"start it: litellm --config config/litellm_config.yaml (expected at {self.s.base_url})",
                    )
                ],
            ) from exc
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise DependencyError(
                "Unexpected response shape from proxy", [ErrorDetail(type="bad_response", msg=str(payload)[:300])]
            ) from exc


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
        self.calls.append({"messages": [dict(m) for m in messages], "model": model, "json_mode": json_mode})
        if not self.responses:
            raise AssertionError("ScriptedBackend ran out of responses")
        nxt = self.responses.popleft()
        return nxt if isinstance(nxt, str) else nxt(messages)
