"""LLM-backed parameter repair for recoverable step failures (PARAMS / DATA)."""

from __future__ import annotations

import json
from typing import Any

from ..errors import ErrorDetail, ErrorReport, LLMOutputError
from ..pipeline import PipelineInputs, PipelineStep, resolve_bindings
from .backends import LLMBackend, LLMSettings
from .prompts import REPAIR_SYSTEM, REPAIR_USER
from .self_correction import CorrectionExhausted, structured_completion


class LLMParamRepairer:
    """Asks an LLM to fix the parameters of a step that failed validation (implements `ParamRepairer`).

    The model sees the located error, the bound inputs' profiles and the component's parameter contract; its answer is validated before
    it is used. Returns ``None`` when no valid repair is produced.
    """

    def __init__(self, backend: LLMBackend, registry: Any, settings: LLMSettings | None = None) -> None:
        self.backend, self.registry, self.s = backend, registry, settings or LLMSettings()

    def repair(
        self, step: PipelineStep, error: ErrorReport, inputs: PipelineInputs, catalog_entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Ask the model for corrected parameters of a failed step.

        The model sees the located error, the profiles of the inputs bound to the step, the component's parameter schema and its documented common mistakes,
        and answers ``{"params": {...}}``. The answer is validated and self-corrected; returns ``None`` when no valid repair is produced.
        """
        comp = self.registry.get(step.component)
        bindings = resolve_bindings(step, comp, inputs)
        bound = {
            p: (inputs.profiles.get(r.split(".", 1)[1]) if r.startswith("$inputs.") else None)
            for p, r in bindings.items()
            if p in comp.spec.inputs
        }
        user = REPAIR_USER.format(
            component=step.component,
            schema=json.dumps(catalog_entry.get("params", {})),
            inputs=inputs.to_prompt(),
            params=json.dumps(step.params),
            error=error.to_llm_feedback(),
            pitfalls=f"Known pitfalls for this component:\n{comp.spec.common_mistakes}"
            if comp.spec.common_mistakes
            else "",
        )

        def parse(data: Any) -> dict[str, Any]:
            if not isinstance(data, dict) or not isinstance(data.get("params"), dict):
                raise LLMOutputError(
                    'Expected {"params": {...}}',
                    [ErrorDetail(loc=("params",), type="missing", msg="top-level 'params' object required")],
                )
            params = comp.parse_params(data["params"])
            static = comp.static_checks(bound, params)  # checked on profiles before touching data
            if static:
                raise LLMOutputError("Repaired params are still invalid", static)
            return params.model_dump(exclude_defaults=True)

        try:
            return structured_completion(
                self.backend,
                REPAIR_SYSTEM,
                user,
                parse,
                model=self.s.repair_model,
                max_attempts=self.s.max_correction_attempts,
                json_mode=self.s.json_mode,
            ).value
        except CorrectionExhausted:
            return None


__all__ = [
    "LLMParamRepairer",
]
