"""Backend-agnostic self-correction loop.

    ask -> extract JSON -> validate (pydantic + domain validators)
        -> on failure: feed the structured ErrorReport back -> ask again

Design choices for small local models (7-14B):
* the conversation is *not* allowed to grow: each retry sends system + task +
  last bad answer + feedback only;
* feedback is a compact JSON list of located errors with hints;
* JSON extraction tolerates code fences, prose around the object and trailing commas.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..errors import ErrorDetail, ErrorReport, FabricError, LLMOutputError, details_from_pydantic
from .backends import LLMBackend, Message

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def extract_json(text: str) -> Any:
    """Return the first JSON object/array found in ``text`` or raise ``LLMOutputError``."""
    if not text or not text.strip():
        raise LLMOutputError(
            "Empty model output",
            [ErrorDetail(type="empty_output", msg="the answer was empty", hint="answer with a single JSON object")],
        )
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    last_err: json.JSONDecodeError | None = None
    for cand in candidates:
        start = min((i for i in (cand.find("{"), cand.find("[")) if i >= 0), default=-1)
        if start < 0:
            continue
        snippet = _balanced(cand, start)
        for attempt in (snippet, _TRAILING_COMMA.sub(r"\1", snippet)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as exc:
                last_err = exc
    if last_err is None:
        raise LLMOutputError(
            "No JSON object in model output",
            [
                ErrorDetail(
                    type="no_json",
                    msg="could not find '{' in the answer",
                    hint="reply with only a JSON object, no prose",
                )
            ],
        )
    raise LLMOutputError(
        "Model output is not valid JSON",
        [
            ErrorDetail(
                type="json_decode",
                msg=f"{last_err.msg} at line {last_err.lineno} column {last_err.colno}",
                hint="use double quotes, no comments, no trailing commas",
            )
        ],
    )


def extract_text(text: str) -> str:
    """Return the model answer stripped of surrounding whitespace; an empty answer raises `LLMOutputError`."""
    if not text or not text.strip():
        raise LLMOutputError("Empty model output", [ErrorDetail(type="empty_output", msg="the answer was empty")])
    return text.strip()


def _balanced(s: str, start: int) -> str:
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return s[start:]  # unbalanced: let json.loads report the precise error


REPAIR_TEMPLATE = """Your previous answer was rejected by the validator.

Validation report:
{feedback}

Fix ONLY the listed problems, keep everything else unchanged, and reply with the complete corrected JSON object only."""


@dataclass
class Attempt:
    number: int
    raw: str
    error: ErrorReport | None = None


@dataclass
class Corrected[T]:
    value: T
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def n_attempts(self) -> int:
        """Number of model calls used, including the successful one."""
        return len(self.attempts)


class CorrectionExhausted(LLMOutputError):
    recoverable = False

    def __init__(self, attempts: list[Attempt]) -> None:
        last = attempts[-1].error
        super().__init__(f"No valid output after {len(attempts)} attempt(s)", last.details if last else [])
        self.attempts = attempts


def structured_completion[T](
    backend: LLMBackend,
    system: str,
    user: str,
    parse: Callable[[Any], T],
    *,
    model: str | None = None,
    max_attempts: int = 3,
    json_mode: bool = True,
    temperature: float | None = None,
    extract: Callable[[str], Any] = extract_json,
    feedback_extra: Callable[[ErrorReport, Any], str] | None = None,
) -> Corrected[T]:
    """Ask, extract, validate; on failure feed the ErrorReport back.

    ``extract`` defaults to JSON extraction; pass ``extract_text`` for free-text answers that still go through
    ``parse`` validation. ``feedback_extra(report, data)`` may append targeted guidance (e.g. a skill's common
    mistakes).
    """
    base: list[Message] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    messages = list(base)
    attempts: list[Attempt] = []
    for n in range(1, max_attempts + 1):
        raw = backend.complete(messages, model=model, json_mode=json_mode, temperature=temperature)
        data = None
        try:
            data = extract(raw)
            value = parse(data)
        except FabricError as exc:
            report = exc.report
        except ValidationError as exc:
            report = LLMOutputError("Output does not match the schema", details_from_pydantic(exc)).report
        else:
            attempts.append(Attempt(n, raw))
            return Corrected(value, attempts)
        attempts.append(Attempt(n, raw, report))
        # slightly raise temperature on retries to escape a stuck mode, capped
        temperature = min((temperature or 0.1) + 0.1, 0.5)
        feedback = REPAIR_TEMPLATE.format(feedback=report.to_llm_feedback())
        if feedback_extra is not None:
            extra = feedback_extra(report, data)
            if extra:
                feedback += "\n\n" + extra
        messages = base + [{"role": "assistant", "content": raw[:4000]}, {"role": "user", "content": feedback}]
    raise CorrectionExhausted(attempts)


__all__ = [
    "Attempt",
    "Corrected",
    "CorrectionExhausted",
    "extract_json",
    "extract_text",
    "structured_completion",
]
