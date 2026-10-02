"""Step interpretation with a *grounding* validator.

The LLM may only cite numbers present in the source JSON. Ungrounded numbers become
located errors (``findings.2``) fixed by the self-correction loop - a cheap,
deterministic hallucination guard. ``grounding_errors`` is reused by agents.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from ..errors import ErrorDetail, LLMOutputError
from ..executor import StepOutcome, StepStatus
from .backends import LLMBackend, LLMSettings
from .prompts import INTERPRETER_SYSTEM, INTERPRETER_USER, compact
from .self_correction import structured_completion


class Interpretation(BaseModel):
    step_id: str
    headline: str = Field(min_length=3, max_length=240)
    findings: list[str] = Field(min_length=1, max_length=6)
    caveats: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["high", "medium", "low"]
    source: Literal["llm", "rules"] = "llm"


class Interpreter(Protocol):
    def interpret(self, outcome: StepOutcome, objective: str, registry: Any) -> Interpretation | None:
        """Interpret the outcome of one step in the light of the objective.

        Returns an `Interpretation` (headline, findings, caveats, confidence), or ``None`` for a step without a result. Interpreters explain results; they never compute them.
        """
        ...


# ------------------------------------------------------------------ grounding
_NUM = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?%?")


def numbers_in(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            yield float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from numbers_in(str(k))
            yield from numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from numbers_in(v)
    elif isinstance(obj, str):
        for tok in re.findall(r"\d+(?:\.\d+)?", obj):
            yield float(tok)


def _grounded(token: str, pool: list[float]) -> bool:
    pct = token.endswith("%")
    t = token.rstrip("%").replace(",", ".")
    x = float(t)
    decimals = len(t.split(".")[1]) if "." in t else 0
    tol = 0.5 * 10 ** (-decimals) * 1.001
    if abs(x) <= 10 and decimals == 0 and not pct:
        return True  # small integers ("2 clusters", "3 groups") are not policed
    return any(abs(abs(v) - abs(x)) <= tol or (pct and abs(v * 100 - abs(x)) <= tol) for v in pool)


def grounding_errors_texts(texts: list[tuple[tuple[str | int, ...], str]], *sources: Any) -> list[ErrorDetail]:
    pool = [v for src in sources for v in numbers_in(src)]
    errors = []
    for loc, text in texts:
        bad = [tok for tok in _NUM.findall(text) if not _grounded(tok, pool)]
        if bad:
            errors.append(
                ErrorDetail(
                    loc=loc,
                    type="ungrounded_number",
                    input=text[:120],
                    msg=f"numbers {bad} do not appear in the source data",
                    hint="copy values from the results (rounding allowed) or remove them",
                )
            )
    return errors


def grounding_errors(interp: Interpretation, *sources: Any) -> list[ErrorDetail]:
    """Return an `ErrorDetail` for every number in the interpretation that does not appear in ``sources``.

    Used to reject invented numbers in headlines, findings and caveats. Small integers are not policed.
    """
    texts: list[tuple[tuple[str | int, ...], str]] = [(("headline",), interp.headline)]
    texts += [(("findings", i), t) for i, t in enumerate(interp.findings)]
    texts += [(("caveats", i), t) for i, t in enumerate(interp.caveats)]
    return grounding_errors_texts(texts, *sources)


# ------------------------------------------------------------------ interpreters
class LLMInterpreter:
    """Interprets a step result with an LLM, then checks the answer is grounded.

    Sends the compacted result and the skill's interpretation guide to the model and parses an `Interpretation`. With ``check_grounding``,
    numbers in the text must appear in the result; violations are fed back for self-correction. Returns ``None`` for steps without a result.
    """

    def __init__(self, backend: LLMBackend, settings: LLMSettings | None = None, check_grounding: bool = True) -> None:
        self.backend, self.s, self.check_grounding = backend, settings or LLMSettings(), check_grounding

    def interpret(self, outcome: StepOutcome, objective: str, registry: Any) -> Interpretation | None:
        """Interpret a step result with the model, using the skill's interpretation guide.

        The model answers a JSON `Interpretation`; with ``check_grounding`` every number in the text must appear in the result or the parameters, otherwise
        the answer is rejected and corrected. Returns ``None`` when the step has no result.
        """
        if outcome.result is None:
            return None
        spec = registry.spec(outcome.component)
        user = INTERPRETER_USER.format(
            objective=objective,
            step_id=outcome.step_id,
            component=spec.name,
            title=spec.title,
            focus=spec.interpretation_guide,
            params=compact(outcome.params),
            result=compact(outcome.result),
        )

        def parse(data: Any) -> Interpretation:
            interp = Interpretation.model_validate({**data, "step_id": outcome.step_id, "source": "llm"})
            if self.check_grounding:
                errs = grounding_errors(interp, outcome.result, outcome.params)
                if errs:
                    raise LLMOutputError("Interpretation cites numbers not present in the result", errs)
            return interp

        return structured_completion(
            self.backend,
            INTERPRETER_SYSTEM,
            user,
            parse,
            model=self.s.interpreter_model,
            max_attempts=self.s.max_correction_attempts,
            json_mode=self.s.json_mode,
            temperature=self.s.temperature,
        ).value


class RuleInterpreter:
    """Deterministic interpretation via each component's ``summarize`` hook; no LLM needed."""

    def interpret(self, outcome: StepOutcome, objective: str, registry: Any) -> Interpretation | None:
        """Interpret a step without a model, from the component's own ``summarize`` (headline and findings).

        Confidence is ``high`` without warnings, ``medium`` with one or two and ``low`` with more; a repaired step adds a caveat. Returns ``None`` for a step without a result.
        """
        r = outcome.result
        if r is None:
            return None
        summary = registry.get(outcome.component).summarize(r) if registry.has(outcome.component) else None
        head, findings = summary or (f"Step '{outcome.step_id}' ({outcome.component}) completed.", [])
        warns = list(r.get("warnings", []))
        if outcome.status == StepStatus.REPAIRED:
            warns.append("parameters were automatically repaired before this step succeeded")
        conf = "high" if not warns else "medium" if len(warns) <= 2 else "low"
        return Interpretation(
            step_id=outcome.step_id,
            headline=(head or "completed")[:240],
            findings=(findings or ["See the result for details."])[:6],
            caveats=warns[:8],
            confidence=conf,
            source="rules",
        )


__all__ = [
    "Interpretation",
    "Interpreter",
    "LLMInterpreter",
    "RuleInterpreter",
    "grounding_errors",
]
