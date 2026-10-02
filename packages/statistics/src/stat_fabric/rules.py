"""Deterministic statistics planner (offline fallback). Registered as planner backend ``stats_rules``."""

from __future__ import annotations

from typing import Any

from agent_fabric.errors import DataValidationError, ErrorDetail
from agent_fabric.llm.planner import PlanningOutcome
from agent_fabric.pipeline import PipelineInputs, PipelinePlan, PipelineStep, parse_plan
from agent_fabric.tabular import ColumnKind, DatasetProfile


class StatsRulePlanner:
    """Heuristic plan from the dataframe profile. Hints: response, factors, time_col, features."""

    name = "stats_rules"

    def __init__(self, registry: Any, hints: dict[str, Any] | None = None) -> None:
        self.registry, self.hints = registry, hints or {}

    def plan(self, objective: str, inputs: PipelineInputs, memory_context: str = "") -> PlanningOutcome:
        """Build a plan from the dataset profile alone, without a model (deterministic baseline and fallback).

        Starts with ``summary`` and adds ``linear_model`` and ``anova`` (needs a numeric response), ``time_series`` (a datetime column and at
        least 12 rows) and ``pca`` followed by ``clustering`` (at least 3 features and 20 rows; 2 features cluster directly) only when the
        columns justify them. Usable columns have at most 30% missing values; categorical factors have 2 to 30 levels. ``hints`` can fix the
        response, features, factors and time column. Raises ``DataValidationError`` when no dataframe input exists. The rules ignore the objective text.
        """
        frames = [n for n, s in inputs.specs.items() if s.type == "dataframe"]
        if not frames:
            raise DataValidationError(
                "stats_rules planner needs a dataframe input",
                [ErrorDetail(loc=("inputs",), type="no_dataframe", msg=f"inputs: {sorted(inputs.specs)}")],
            )
        src = frames[0]
        profile: DatasetProfile = inputs.profiles[src]  # type: ignore[assignment]
        h = self.hints
        ok = lambda c: profile.column(c) is not None and profile.column(c).missing_ratio <= 0.3  # noqa: E731
        num = [c for c in profile.names(ColumnKind.NUMERIC) if ok(c) and profile.column(c).n_unique > 1]
        cat = [c for c in profile.names(ColumnKind.CATEGORICAL) if ok(c) and 2 <= profile.column(c).n_unique <= 30]
        dt = [c for c in profile.names(ColumnKind.DATETIME) if ok(c)]
        data = {"data": f"$inputs.{src}"}
        steps = [PipelineStep(id="summary", component="summary", inputs=data, rationale="baseline description")]
        response = h.get("response") or (num[-1] if num else None)
        features = h.get("features") or [c for c in num if c != response]
        factors = h.get("factors") or cat[:1]
        if response and response in num:
            preds = features[:8] + factors[:1]
            if preds:
                steps.append(
                    PipelineStep(
                        id="regression",
                        component="linear_model",
                        inputs=data,
                        params={"response": response, "predictors": preds},
                    )
                )
            if factors:
                steps.append(
                    PipelineStep(
                        id="anova",
                        component="anova",
                        inputs=data,
                        params={"response": response, "factors": factors[:2]},
                    )
                )
        time_col = h.get("time_col") or (dt[0] if dt else None)
        if time_col and response and profile.n_rows >= 12:
            steps.append(
                PipelineStep(
                    id="time_series",
                    component="time_series",
                    inputs=data,
                    params={"time_col": time_col, "value_col": response},
                )
            )
        if len(features) >= 3:
            steps.append(PipelineStep(id="pca", component="pca", inputs=data, params={"features": features}))
            if profile.n_rows >= 20:
                steps.append(PipelineStep(id="clusters", component="clustering", inputs={"matrix": "pca.scores"}))
        elif len(features) == 2 and profile.n_rows >= 20:
            steps.append(
                PipelineStep(id="clusters", component="clustering", inputs=data, params={"features": features})
            )
        outputs = {"cluster_labels": "clusters.labels"} if any(s.id == "clusters" for s in steps) else {}
        plan = PipelinePlan(
            objective=objective if len(objective) >= 3 else "statistical analysis",
            steps=[s for s in steps if self.registry.has(s.component)],
            outputs=outputs,
        )
        return PlanningOutcome(plan=parse_plan(plan, self.registry, inputs), planner=self.name)


def register_planner_backend() -> None:
    """Register the ``stats_rules`` planner backend (no LLM; used as the fallback of the ``statistician`` agent)."""
    from agent_fabric.agents.fabric import planner_builder

    planner_builder("stats_rules", lambda f, spec, backend: StatsRulePlanner(f.registry, spec.options.get("hints")))


__all__ = [
    "StatsRulePlanner",
    "register_planner_backend",
]
