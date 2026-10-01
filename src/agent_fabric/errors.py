"""Error taxonomy for the fabric.

Every failure that crosses a module boundary is a ``FabricError`` carrying a
typed ``ErrorReport``. Reports are serialisable (API responses, memory, logs) and
can be rendered as compact feedback for the LLM self-correction loop.
"""

from __future__ import annotations

import difflib
import json
from enum import StrEnum
from typing import Any, ClassVar
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field, ValidationError


class ErrorCategory(StrEnum):
    SPEC = "spec"                # component spec / contract is broken (developer error)
    PLAN = "plan"                # analysis plan is structurally invalid
    PARAMS = "params"            # step parameters do not match the component's Params model
    DATA = "data"                # an input artifact does not satisfy the port constraints
    EXECUTION = "execution"      # numerical / library failure while computing
    LLM_OUTPUT = "llm_output"    # model returned unparsable or invalid output
    DEPENDENCY = "dependency"    # upstream step failed or optional package missing
    AGENT = "agent"              # agent tree config or delegation is invalid
    BUDGET = "budget"            # depth / LLM-call / delegation budget exhausted


class ErrorDetail(BaseModel):
    loc: tuple[str | int, ...] = ()
    type: str
    msg: str
    input: Any = None
    hint: str | None = None


class ErrorReport(BaseModel):
    category: ErrorCategory
    message: str
    component: str | None = None
    step_id: str | None = None
    recoverable: bool = False
    details: list[ErrorDetail] = Field(default_factory=list)

    def to_llm_feedback(self, max_details: int = 8) -> str:
        """Compact, deterministic feedback block for small local models."""
        payload = {
            "error_category": self.category.value,
            "message": self.message,
            "step_id": self.step_id,
            "component": self.component,
            "errors": [
                {k: v for k, v in {
                    "loc": ".".join(str(p) for p in d.loc) or None,
                    "type": d.type,
                    "msg": d.msg,
                    "hint": d.hint,
                }.items() if v is not None}
                for d in self.details[:max_details]
            ],
        }
        if len(self.details) > max_details:
            payload["omitted_errors"] = len(self.details) - max_details
        return json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False, indent=1)


class FabricError(Exception):
    category: ClassVar[ErrorCategory] = ErrorCategory.EXECUTION
    recoverable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        details: Sequence[ErrorDetail] | None = None,
        *,
        component: str | None = None,
        step_id: str | None = None,
        recoverable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = list(details or [])
        self.component = component
        self.step_id = step_id
        self._recoverable = self.recoverable if recoverable is None else recoverable

    @property
    def report(self) -> ErrorReport:
        return ErrorReport(
            category=self.category,
            message=self.message,
            component=self.component,
            step_id=self.step_id,
            recoverable=self._recoverable,
            details=self.details,
        )

    def with_context(self, *, component: str | None = None, step_id: str | None = None) -> FabricError:
        self.component = self.component or component
        self.step_id = self.step_id or step_id
        return self

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        if not self.details:
            return self.message
        lines = [self.message] + [
            f"  - {'.'.join(map(str, d.loc)) or '<root>'}: {d.msg}" + (f" (hint: {d.hint})" if d.hint else "")
            for d in self.details
        ]
        return "\n".join(lines)


class SpecError(FabricError):
    category = ErrorCategory.SPEC


class PlanValidationError(FabricError):
    category = ErrorCategory.PLAN
    recoverable = True


class ParamsValidationError(FabricError):
    category = ErrorCategory.PARAMS
    recoverable = True


class DataValidationError(FabricError):
    category = ErrorCategory.DATA
    recoverable = True


class ComponentExecutionError(FabricError):
    category = ErrorCategory.EXECUTION


class LLMOutputError(FabricError):
    category = ErrorCategory.LLM_OUTPUT
    recoverable = True


class DependencyError(FabricError):
    category = ErrorCategory.DEPENDENCY


class AgentConfigError(FabricError):
    category = ErrorCategory.AGENT


class DelegationError(FabricError):
    """A supervisor produced an invalid delegation plan (fixed by self-correction)."""

    category = ErrorCategory.AGENT
    recoverable = True


class BudgetExceeded(FabricError):
    category = ErrorCategory.BUDGET


class MissingOptionalDependency(DependencyError):
    def __init__(self, package: str, extra: str) -> None:
        super().__init__(
            f"Optional dependency '{package}' is not installed.",
            [ErrorDetail(type="missing_dependency", msg=f"import of '{package}' failed",
                         hint=f"pip install 'agent-fabric[{extra}]'")],
        )


# --------------------------------------------------------------------------- helpers

def _preview(value: Any, limit: int = 80) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def details_from_pydantic(exc: ValidationError, prefix: Iterable[str | int] = ()) -> list[ErrorDetail]:
    prefix = tuple(prefix)
    out: list[ErrorDetail] = []
    for err in exc.errors(include_url=False):
        hint = None
        if err["type"] == "extra_forbidden":
            hint = "remove this field; it is not part of the schema"
        elif err["type"] == "missing":
            hint = "this field is required"
        elif err["type"].startswith("literal_error"):
            hint = f"allowed values: {err.get('ctx', {}).get('expected')}"
        out.append(ErrorDetail(loc=prefix + tuple(err["loc"]), type=err["type"], msg=err["msg"],
                               input=_preview(err.get("input")), hint=hint))
    return out


def suggest(name: str, candidates: Iterable[str]) -> str | None:
    """'did you mean ...?' hint for misspelled names (components, ports, agents, columns)."""
    matches = difflib.get_close_matches(str(name), list(candidates), n=3, cutoff=0.6)
    return f"did you mean {', '.join(repr(m) for m in matches)}?" if matches else None
