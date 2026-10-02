"""Deterministic pipeline executor.

LLMs never compute: they plan, repair parameters and interpret. The executor runs a
validated plan in topological order over an ``ArtifactStore``, isolates failures
per step, skips dependents of failed steps and - if a ``ParamRepairer`` is set -
gives recoverable failures (PARAMS / DATA) a bounded number of repair attempts.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, PrivateAttr

from .component import ArtifactStore, StepContext
from .errors import DependencyError, ErrorCategory, ErrorDetail, ErrorReport, FabricError
from .pipeline import PipelineInputs, PipelinePlan, PipelineStep, resolve_bindings


class StepStatus(StrEnum):
    OK = "ok"
    REPAIRED = "repaired"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepOutcome(BaseModel):
    step_id: str
    component: str
    status: StepStatus
    params: dict[str, Any]
    bindings: dict[str, str] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: ErrorReport | None = None
    repair_history: list[ErrorReport] = Field(default_factory=list)
    duration_s: float = 0.0


class PipelineReport(BaseModel):
    objective: str
    outcomes: list[StepOutcome]
    outputs: dict[str, str] = Field(default_factory=dict)
    _store: ArtifactStore | None = PrivateAttr(default=None)

    @property
    def ok(self) -> bool:
        """Whether every step succeeded (a repaired step counts as success)."""
        return all(o.status in (StepStatus.OK, StepStatus.REPAIRED) for o in self.outcomes)

    @property
    def artifacts(self) -> ArtifactStore:
        """The `ArtifactStore` of the run, holding every emitted artifact keyed ``<step_id>.<port>`` (empty if nothing ran)."""
        return self._store or ArtifactStore()

    def by_id(self, step_id: str) -> StepOutcome:
        """The outcome of one step by id (raises ``StopIteration`` for an unknown id)."""
        return next(o for o in self.outcomes if o.step_id == step_id)

    def failures(self) -> list[StepOutcome]:
        """Outcomes of steps that failed or were skipped, in execution order."""
        return [o for o in self.outcomes if o.status in (StepStatus.FAILED, StepStatus.SKIPPED)]

    def output_values(self) -> dict[str, Any]:
        """The plan's exposed outputs as ``{name: value}``; outputs whose artifact was not produced are left out."""
        store = self.artifacts
        return {k: store.get(r) for k, r in self.outputs.items() if store.has(r)}


class ParamRepairer(Protocol):
    """Fixes the parameters of a step that failed validation (implemented by `LLMParamRepairer`)."""

    def repair(
        self, step: PipelineStep, error: ErrorReport, inputs: PipelineInputs, catalog_entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Propose corrected parameters for a step that failed with a recoverable ``params``/``data`` error.

        Receives the failing step, the located error, the pipeline inputs and the component's catalogue entry. Returns the new
        ``params`` dict, or ``None`` to give up; the executor revalidates whatever it returns.
        """
        ...


REPAIRABLE = {ErrorCategory.PARAMS, ErrorCategory.DATA}


class PipelineExecutor:
    """Runs a validated `PipelinePlan` step by step in topological order.

    Each step executes through `Component.execute`; results go to an `ArtifactStore`. A failed step skips its dependents; with
    ``fail_policy="fail_fast"`` the run stops at the first failure. When a `ParamRepairer` is given, parameter and data errors are repaired
    up to ``max_repairs`` times. ``llm`` and ``llm_settings`` are forwarded to ``runtime: prompt`` steps and ``on_step`` is called after
    each step. `run` returns a `PipelineReport`.
    """

    def __init__(
        self,
        registry: Any,
        *,
        fail_policy: Literal["continue", "fail_fast"] = "continue",
        repairer: ParamRepairer | None = None,
        max_repairs: int = 1,
        llm: Any = None,
        llm_settings: Any = None,
        on_step: Any = None,
    ) -> None:
        self.registry, self.fail_policy, self.repairer, self.max_repairs = registry, fail_policy, repairer, max_repairs
        self.llm, self.llm_settings = llm, llm_settings  # for 'runtime: prompt' steps (agents pass a metered backend)
        self.on_step = on_step  # optional callback(StepOutcome) after each step - UIs

    def run(self, plan: PipelinePlan, inputs: dict[str, Any] | PipelineInputs, depth: int = 0) -> PipelineReport:
        """Execute a plan and return its `PipelineReport`.

        Steps run in topological order. A step whose dependencies failed or were skipped is skipped with a ``DependencyError``; with
        ``fail_policy="fail_fast"`` every step after the first failure is skipped. A recoverable parameter or data failure is passed to the
        repairer (when one is configured) up to ``max_repairs`` times. ``inputs`` may be raw values (their artifact types are inferred) or ready
        `PipelineInputs`. ``depth`` is the nesting level when running as a step of another pipeline.
        """
        pin = inputs if isinstance(inputs, PipelineInputs) else PipelineInputs.from_values(inputs, self.registry.types)
        store = ArtifactStore({f"$inputs.{k}": v for k, v in pin.values.items()})
        outcomes: dict[str, StepOutcome] = {}
        catalog = {c["name"]: c for c in self.registry.catalog()}
        halted = False
        for step in plan.topological_order():
            deps = plan.all_deps(step)
            bad = sorted(d for d in deps if outcomes[d].status in (StepStatus.FAILED, StepStatus.SKIPPED))
            if halted or bad:
                err = DependencyError(
                    "halted after earlier failure (fail_fast)" if halted else f"upstream step(s) failed: {bad}",
                    [
                        ErrorDetail(loc=("depends_on",), type="upstream_failed", msg=f"'{d}' did not succeed")
                        for d in bad
                    ],
                    component=step.component,
                    step_id=step.id,
                )
                outcomes[step.id] = StepOutcome(
                    step_id=step.id,
                    component=step.component,
                    status=StepStatus.SKIPPED,
                    params=step.params,
                    error=err.report,
                )
                continue
            outcomes[step.id] = self._run_step(
                step, pin, store, catalog.get(step.component, {}), depth, objective=plan.objective
            )
            if self.on_step is not None:
                self.on_step(outcomes[step.id])
            if outcomes[step.id].status == StepStatus.FAILED and self.fail_policy == "fail_fast":
                halted = True
        report = PipelineReport(
            objective=plan.objective, outcomes=[outcomes[s.id] for s in plan.steps], outputs=plan.outputs
        )
        report._store = store
        return report

    def _run_step(
        self,
        step: PipelineStep,
        pin: PipelineInputs,
        store: ArtifactStore,
        catalog_entry: dict[str, Any],
        depth: int,
        objective: str = "",
    ) -> StepOutcome:
        t0 = time.perf_counter()
        params, history = dict(step.params), []
        bindings: dict[str, str] = {}

        def outcome(status: StepStatus, **kw: Any) -> StepOutcome:
            return StepOutcome(
                step_id=step.id,
                component=step.component,
                status=status,
                params=params,
                bindings=bindings,
                repair_history=history,
                duration_s=round(time.perf_counter() - t0, 4),
                **kw,
            )

        for attempt in range(self.max_repairs + 1):
            try:
                comp = self.registry.get(step.component)
                bindings = resolve_bindings(step, comp, pin)
                missing = [r for r in bindings.values() if not store.has(r)]
                if missing:
                    raise DependencyError(
                        f"artifacts not available: {missing}",
                        [
                            ErrorDetail(loc=("inputs",), type="missing_artifact", msg=f"'{r}' was not produced")
                            for r in missing
                        ],
                    )
                values = {port: store.get(ref) for port, ref in bindings.items()}
                ctx = StepContext(
                    store,
                    step.id,
                    comp.spec,
                    self.registry.types,
                    depth,
                    llm=self.llm,
                    llm_settings=self.llm_settings,
                    objective=objective,
                    on_step=self.on_step,
                )
                result = comp.execute(values, params, ctx)
                return outcome(StepStatus.REPAIRED if history else StepStatus.OK, result=result.model_dump(mode="json"))
            except FabricError as exc:
                report = exc.with_context(component=step.component, step_id=step.id).report
                can_repair = (
                    self.repairer is not None
                    and attempt < self.max_repairs
                    and report.recoverable
                    and report.category in REPAIRABLE
                )
                if not can_repair:
                    return outcome(StepStatus.FAILED, error=report)
                new = self.repairer.repair(step.model_copy(update={"params": params}), report, pin, catalog_entry)
                if not new or new == params:
                    return outcome(StepStatus.FAILED, error=report)
                history.append(report)
                params = new
        raise AssertionError("unreachable")  # pragma: no cover


__all__ = [
    "ParamRepairer",
    "PipelineExecutor",
    "PipelineReport",
    "StepOutcome",
    "StepStatus",
]
