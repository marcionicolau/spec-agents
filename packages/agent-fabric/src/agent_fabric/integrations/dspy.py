"""DSPy integration: generic pipeline-planning program + optimisation.

The runtime validators (``parse_scoped``) are also the optimisation metric, so
``BootstrapFewShot`` selects demonstrations that make *your* local model emit valid plans.
Registers planner backend ``dspy`` (``kind: planner, backend: dspy``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ..errors import MissingOptionalDependency, PlanValidationError
from ..evals import score_plan
from ..llm.backends import LLMSettings
from ..llm.planner import PlanningOutcome, parse_scoped
from ..pipeline import PipelineInputs, PipelinePlan

try:
    import dspy
except ImportError:  # pragma: no cover
    dspy = None


def _require() -> None:
    if dspy is None:
        raise MissingOptionalDependency("dspy", "dspy")


def configure_dspy(settings: LLMSettings | None = None, model: str | None = None) -> Any:
    """Point DSPy at the LiteLLM proxy using the planner model of ``settings`` (or ``model``); returns the ``dspy.LM``."""
    _require()
    s = settings or LLMSettings()
    lm = dspy.LM(
        f"openai/{model or s.planner_model}",
        api_base=s.base_url,
        api_key=s.api_key,
        temperature=s.temperature,
        cache=False,
    )
    dspy.configure(lm=lm)
    return lm


if dspy is not None:

    class PlanPipeline(dspy.Signature):
        """Design a pipeline from the catalogue. Use only listed components, parameters, ports and columns.
        Reference data as "$inputs.<name>" or "<step_id>.<output>". If validator_feedback is not 'none',
        fix exactly those errors."""

        objective: str = dspy.InputField()
        pipeline_inputs: str = dspy.InputField()
        catalog: str = dspy.InputField(desc="JSON list of components with params, inputs and outputs")
        validator_feedback: str = dspy.InputField(desc="JSON error report from the previous attempt, or 'none'")
        plan: PipelinePlan = dspy.OutputField()

    class DSPyPlanProgram(dspy.Module):
        def __init__(
            self, registry: Any, domains: Iterable[str] | None = None, max_attempts: int = 3, reasoning: bool = True
        ) -> None:
            super().__init__()
            self.registry, self.domains, self.max_attempts = registry, list(domains) if domains else None, max_attempts
            self.predict = dspy.ChainOfThought(PlanPipeline) if reasoning else dspy.Predict(PlanPipeline)

        def forward(self, objective: str, inputs: PipelineInputs) -> Any:
            catalog = json.dumps(self.registry.catalog(self.domains), ensure_ascii=False)
            feedback, rejected = "none", []
            for _ in range(self.max_attempts):
                pred = self.predict(
                    objective=objective,
                    pipeline_inputs=inputs.to_prompt(),
                    catalog=catalog,
                    validator_feedback=feedback,
                )
                try:
                    return dspy.Prediction(
                        plan=parse_scoped(pred.plan, self.registry, inputs, self.domains), rejected=rejected, valid=True
                    )
                except PlanValidationError as exc:
                    rejected.append(exc.report)
                    feedback = exc.report.to_llm_feedback()
            return dspy.Prediction(plan=None, rejected=rejected, valid=False)

else:  # pragma: no cover
    PlanPipeline = DSPyPlanProgram = None  # type: ignore[assignment,misc]


def plan_metric(example: Any, pred: Any, trace: Any = None) -> float:
    """Same score as the regression evals (``agent_fabric.evals.score_plan``)."""
    comps = [s.component for s in pred.plan.steps] if getattr(pred, "valid", False) and pred.plan is not None else None
    score = score_plan(
        comps,
        len(getattr(pred, "rejected", []) or []),
        getattr(example, "expected_components", None) or [],
        getattr(example, "forbidden_components", None) or [],
    )
    return score if trace is None else float(score >= 0.9)


def optimize_planner(program: Any, trainset: list[Any], max_demos: int = 3) -> Any:
    """Optimise a DSPy planning program with ``BootstrapFewShot``.

    The plan validators are the metric (`plan_metric`), so the selected demonstrations are the ones that make the local model emit valid
    plans. ``trainset`` is a list of DSPy examples; returns the compiled program.
    """
    _require()
    return dspy.BootstrapFewShot(
        metric=plan_metric, max_bootstrapped_demos=max_demos, max_labeled_demos=max_demos
    ).compile(program, trainset=trainset)


class DSPyPlanner:
    """Planner backed by a DSPy program (planner backend ``dspy``).

    Validates every proposed plan with the same validators as the other planners, retrying up to ``max_attempts``. Requires the ``dspy``
    extra.
    """

    name = "dspy"

    def __init__(
        self, registry: Any, program: Any = None, domains: Iterable[str] | None = None, max_attempts: int = 3
    ) -> None:
        _require()
        self.program = program or DSPyPlanProgram(registry, domains, max_attempts)

    def plan(self, objective: str, inputs: PipelineInputs, memory_context: str = "") -> PlanningOutcome:
        pred = self.program(
            objective=objective + (f"\nPrevious runs:\n{memory_context}" if memory_context else ""), inputs=inputs
        )
        if not pred.valid:
            raise PlanValidationError(
                "DSPy planner could not produce a valid plan",
                pred.rejected[-1].details if pred.rejected else [],
                recoverable=False,
            )
        return PlanningOutcome(plan=pred.plan, planner="dspy", attempts=len(pred.rejected) + 1, rejected=pred.rejected)


def _register() -> None:
    from ..agents.fabric import planner_builder

    def make(f: Any, spec: Any, backend: Any) -> DSPyPlanner:
        if spec.options.get("configure", True) and "lm" not in spec.options:
            configure_dspy(f.settings_for(spec))
        program = DSPyPlanProgram(f.registry, spec.domains or None, f.settings_for(spec).max_correction_attempts)
        if spec.options.get("compiled_path"):
            program.load(spec.options["compiled_path"])
        return DSPyPlanner(f.registry, program=program)

    planner_builder("dspy", make)


if dspy is not None:
    _register()


__all__ = [
    "DSPyPlanner",
    "configure_dspy",
    "optimize_planner",
    "plan_metric",
]
