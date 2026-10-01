"""Planners turn an objective + pipeline inputs into a validated ``PipelinePlan``.

* ``LLMPlanner``        - any LLMBackend + fabric self-correction loop
* ``PydanticAIPlanner`` - PydanticAI agent; validation errors -> ``ModelRetry``
* ``TemplatePlanner``   - instantiates a registered PipelineSpec (deterministic fallback)
* domain packs may add rule planners (e.g. ``stat_fabric.rules.StatsRulePlanner``)

All planners return plans that passed ``parse_plan`` and are scoped to their domains.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..errors import ErrorDetail, ErrorReport, MissingOptionalDependency, PlanValidationError, suggest
from ..pipeline import MAX_STEPS, PipelineInputs, PipelinePlan, parse_plan
from .backends import LLMBackend, LLMSettings
from .prompts import PLANNER_SYSTEM, PLANNER_USER
from .self_correction import structured_completion


class PlanningOutcome(BaseModel):
    plan: PipelinePlan
    planner: str
    attempts: int = 1
    rejected: list[ErrorReport] = Field(default_factory=list)


class Planner(Protocol):
    def plan(self, objective: str, inputs: PipelineInputs, memory_context: str = "") -> PlanningOutcome: ...


def parse_scoped(raw: Any, registry: Any, inputs: PipelineInputs, domains: Iterable[str] | None) -> PipelinePlan:
    plan = parse_plan(raw, registry, inputs)
    if domains:
        allowed = registry.names(domains)
        errs = [
            ErrorDetail(
                loc=("steps", i, "component"),
                type="component_out_of_scope",
                input=s.component,
                msg=f"'{s.component}' is outside this planner's domains {sorted(domains)}",
                hint=suggest(s.component, allowed) or f"use one of {allowed}",
            )
            for i, s in enumerate(plan.steps)
            if s.component not in allowed
        ]
        if errs:
            raise PlanValidationError("Plan uses components outside the allowed domains", errs)
    return plan


def pitfalls_for_plan(registry: Any, max_components: int = 3) -> Callable[[ErrorReport, Any], str]:
    """Feedback hook: append the 'Common mistakes' section of the components the rejected plan got wrong."""

    def extra(report: ErrorReport, data: Any) -> str:
        steps = data.get("steps", []) if isinstance(data, dict) else []
        names: list[str] = []
        for d in report.details:
            if len(d.loc) > 1 and d.loc[0] == "steps" and isinstance(d.loc[1], int) and d.loc[1] < len(steps):
                comp = steps[d.loc[1]].get("component") if isinstance(steps[d.loc[1]], dict) else None
                if comp and registry.has(comp) and comp not in names:
                    names.append(comp)
        blocks = [
            f"[{n}]\n{registry.spec(n).common_mistakes}"
            for n in names[:max_components]
            if registry.spec(n).common_mistakes
        ]
        return ("Known pitfalls of the components involved:\n" + "\n\n".join(blocks)) if blocks else ""

    return extra


def planner_prompts(
    objective: str, inputs: PipelineInputs, registry: Any, domains: Iterable[str] | None, memory_context: str
) -> tuple[str, str]:
    memory = f"\nPrevious runs in this session (context only):\n{memory_context}" if memory_context else ""
    user = PLANNER_USER.format(
        objective=objective,
        inputs=inputs.to_prompt(),
        catalog=json.dumps(registry.catalog(domains), ensure_ascii=False),
        memory=memory,
    )
    return PLANNER_SYSTEM.format(max_steps=MAX_STEPS), user


class LLMPlanner:
    """Plans a pipeline with an LLM, validating and self-correcting the proposal.

    The model sees a catalogue of the components of the allowed ``domains``; its JSON plan is validated (structure, registry, ports, types,
    static constraints) and rejected plans are returned to it with located errors until a plan is valid or the attempts run out.
    `plan` returns a `PlanningOutcome`.
    """

    name = "llm"

    def __init__(
        self,
        backend: LLMBackend,
        registry: Any,
        settings: LLMSettings | None = None,
        domains: Iterable[str] | None = None,
    ) -> None:
        self.backend, self.registry, self.s = backend, registry, settings or LLMSettings()
        self.domains = list(domains) if domains else None

    def plan(self, objective: str, inputs: PipelineInputs, memory_context: str = "") -> PlanningOutcome:
        system, user = planner_prompts(objective, inputs, self.registry, self.domains, memory_context)
        res = structured_completion(
            self.backend,
            system,
            user,
            lambda d: parse_scoped(d, self.registry, inputs, self.domains),
            model=self.s.planner_model,
            max_attempts=self.s.max_correction_attempts,
            json_mode=self.s.json_mode,
            temperature=self.s.temperature,
            feedback_extra=pitfalls_for_plan(self.registry),
        )
        return PlanningOutcome(
            plan=res.value,
            planner=self.name,
            attempts=res.n_attempts,
            rejected=[a.error for a in res.attempts if a.error],
        )


class PydanticAIPlanner:
    """PydanticAI-native variant: the output validator raises ``ModelRetry`` with the ErrorReport."""

    name = "pydantic_ai"

    def __init__(
        self,
        registry: Any,
        settings: LLMSettings | None = None,
        model: Any = None,
        domains: Iterable[str] | None = None,
    ) -> None:
        try:
            import pydantic_ai  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise MissingOptionalDependency("pydantic-ai-slim", "pydantic-ai") from exc
        self.registry, self.s, self._model = registry, settings or LLMSettings(), model
        self.domains = list(domains) if domains else None

    def build_model(self) -> Any:
        if self._model is not None:
            return self._model
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            self.s.planner_model, provider=OpenAIProvider(base_url=self.s.base_url, api_key=self.s.api_key)
        )

    def plan(self, objective: str, inputs: PipelineInputs, memory_context: str = "") -> PlanningOutcome:
        from pydantic_ai import Agent, ModelRetry, RunContext
        from pydantic_ai.output import NativeOutput, PromptedOutput, ToolOutput

        system, user = planner_prompts(objective, inputs, self.registry, self.domains, memory_context)
        wrap = {"prompted": PromptedOutput, "tool": ToolOutput, "native": NativeOutput}[self.s.pydantic_ai_output_mode]
        agent = Agent(
            self.build_model(),
            output_type=wrap(PipelinePlan),
            instructions=system,
            deps_type=PipelineInputs,
            retries=self.s.max_correction_attempts,
            model_settings={"temperature": self.s.temperature},
        )
        rejected: list[ErrorReport] = []

        @agent.output_validator
        def _validate(ctx: RunContext[PipelineInputs], plan: PipelinePlan) -> PipelinePlan:
            try:
                return parse_scoped(plan, self.registry, ctx.deps, self.domains)
            except PlanValidationError as exc:
                rejected.append(exc.report)
                raise ModelRetry(exc.report.to_llm_feedback()) from exc

        result = agent.run_sync(user, deps=inputs)
        return PlanningOutcome(plan=result.output, planner=self.name, attempts=len(rejected) + 1, rejected=rejected)


class TemplatePlanner:
    """Deterministic: instantiate a registered PipelineSpec with fixed params."""

    name = "template"

    def __init__(self, registry: Any, pipeline: str, params: dict[str, Any] | None = None) -> None:
        self.registry, self.pspec, self.params = registry, registry.pipeline(pipeline), params or {}

    def plan(self, objective: str, inputs: PipelineInputs, memory_context: str = "") -> PlanningOutcome:
        raw = self.pspec.instantiate(self.params)
        raw["objective"] = objective if len(objective) >= 3 else raw["objective"]
        return PlanningOutcome(plan=parse_plan(raw, self.registry, inputs), planner=f"template:{self.pspec.name}")


__all__ = [
    "LLMPlanner",
    "Planner",
    "PlanningOutcome",
    "PydanticAIPlanner",
    "TemplatePlanner",
]
