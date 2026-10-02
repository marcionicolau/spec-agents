"""Planner regression evals: catch behaviour changes caused by edits to SKILL.md / AGENT.md bodies.

A body edit changes prompts, not code - unit tests won't notice. Run these cases against the
real proxy before merging guidance changes (and after swapping a model in litellm_config.yaml)::

    cases = load_cases("evals/planner_cases.yaml")
    report = evaluate_planner(planner, cases, {"trial": PipelineInputs.from_values({"data": df}, types)})
    assert report.passed, report.table()

The same score is the DSPy optimisation metric (``integrations.dspy.plan_metric``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .errors import FabricError


class PlannerCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    objective: str
    inputs: str = Field(description="key of the PipelineInputs fixture to use")
    expected_components: list[str] = Field(default_factory=list)
    forbidden_components: list[str] = Field(default_factory=list)
    min_score: float = Field(0.8, ge=0, le=1)


class CaseResult(BaseModel):
    name: str
    score: float
    passed: bool
    attempts: int = 0
    components: list[str] = Field(default_factory=list)
    error: str | None = None


class EvalReport(BaseModel):
    results: list[CaseResult]

    @property
    def mean_score(self) -> float:
        """Mean case score rounded to 4 decimals (``0.0`` without results)."""
        return round(sum(r.score for r in self.results) / len(self.results), 4) if self.results else 0.0

    @property
    def passed(self) -> bool:
        """Whether every case passed."""
        return all(r.passed for r in self.results)

    def table(self) -> str:
        """Fixed-width text table: one row per case (score, pass/fail, planner attempts, components or error) and the mean."""
        rows = [f"{'case':28} {'score':>5}  ok  attempts  components"]
        rows += [
            f"{r.name:28} {r.score:5.2f}  {'✔' if r.passed else '✘'}   {r.attempts:>8}  "
            f"{', '.join(r.components) or r.error or ''}"
            for r in self.results
        ]
        rows.append(f"mean {self.mean_score:.3f}")
        return "\n".join(rows)


def score_plan(
    components: Iterable[str] | None, n_rejected: int, expected: Iterable[str] = (), forbidden: Iterable[str] = ()
) -> float:
    """0 if no valid plan; 0.7 valid + 0.1 first try + 0.2 x expected coverage; -0.3 per forbidden hit."""
    if components is None:
        return 0.0
    got, exp, forb = set(components), set(expected), set(forbidden)
    score = 0.7 + (0.1 if n_rejected == 0 else 0.0) + 0.2 * (len(exp & got) / len(exp) if exp else 1.0)
    score -= 0.3 * len(forb & got)
    return round(max(score, 0.0), 4)


def load_cases(path: str | Path) -> list[PlannerCase]:
    """Load planner regression cases from a YAML file (a list, or a mapping with a ``cases`` key)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    items = raw.get("cases", []) if isinstance(raw, dict) else raw
    return [PlannerCase.model_validate(c) for c in items]


def evaluate_planner(planner: Any, cases: list[PlannerCase], inputs: dict[str, Any]) -> EvalReport:
    """Run a planner over regression cases and score each resulting plan.

    ``cases`` come from `load_cases`; ``inputs`` maps each case's ``inputs`` name to `PipelineInputs`. The score rewards valid plans, a
    valid first attempt and expected components, and penalises forbidden ones (the same score is the DSPy metric). Planner errors are
    recorded per case instead of aborting the run. Returns an `EvalReport`.
    """
    results = []
    for case in cases:
        try:
            out = planner.plan(case.objective, inputs[case.inputs])
            comps = [s.component for s in out.plan.steps]
            score = score_plan(comps, len(out.rejected), case.expected_components, case.forbidden_components)
            results.append(
                CaseResult(
                    name=case.name, score=score, passed=score >= case.min_score, attempts=out.attempts, components=comps
                )
            )
        except FabricError as exc:
            results.append(
                CaseResult(name=case.name, score=0.0, passed=False, error=f"{exc.category.value}: {exc.message}")
            )
    return EvalReport(results=results)


# ------------------------------------------------------------------ baselines (regression gate for deterministic suites)
DEFAULT_TOLERANCE = 0.02


class BaselineIssue(BaseModel):
    severity: Literal["regression", "improvement", "new", "missing"]
    suite: str
    metric: str
    msg: str

    def __str__(self) -> str:
        return f"{self.severity.upper():11} {self.suite}.{self.metric}: {self.msg}"


def load_baselines(path: str | Path) -> dict[str, Any]:
    """Read the eval baseline file (JSON); a missing file yields an empty baseline with the default tolerance."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"tolerance": DEFAULT_TOLERANCE, "suites": {}}


def save_baselines(path: str | Path, data: dict[str, Any]) -> None:
    """Write the eval baseline file as stable, sorted JSON so diffs stay reviewable."""
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_baseline(
    suite: str, current: dict[str, float], baselines: dict[str, Any], tolerance: float | None = None
) -> list[BaselineIssue]:
    """Compare a suite's metrics to its baseline.

    Regressions are metrics below ``baseline - tolerance``; metrics well above it are reported as improvements
    (refresh the baseline in the same PR so the gain is protected); unknown/missing metrics are reported too.
    """
    tol = tolerance if tolerance is not None else float(baselines.get("tolerance", DEFAULT_TOLERANCE))
    base: dict[str, float] = baselines.get("suites", {}).get(suite, {})
    issues: list[BaselineIssue] = []
    for metric, was in base.items():
        if metric not in current:
            issues.append(BaselineIssue(severity="missing", suite=suite, metric=metric, msg="no longer produced"))
        elif current[metric] < was - tol:
            issues.append(
                BaselineIssue(
                    severity="regression",
                    suite=suite,
                    metric=metric,
                    msg=f"{current[metric]:.3f} < baseline {was:.3f} - tolerance {tol:g}",
                )
            )
        elif current[metric] > was + tol:
            issues.append(
                BaselineIssue(
                    severity="improvement",
                    suite=suite,
                    metric=metric,
                    msg=f"{current[metric]:.3f} > baseline {was:.3f}: refresh the baseline",
                )
            )
    for metric in current.keys() - base.keys():
        issues.append(BaselineIssue(severity="new", suite=suite, metric=metric, msg="not in the baseline yet"))
    return issues


__all__ = [
    "BaselineIssue",
    "CaseResult",
    "EvalReport",
    "PlannerCase",
    "compare_baseline",
    "evaluate_planner",
    "load_baselines",
    "load_cases",
    "save_baselines",
    "score_plan",
]
