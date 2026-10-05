"""Explore a dataset with the statistics pack: summary, PCA and clustering, all computed by code."""

from __future__ import annotations

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from stat_fabric.domain import register
from stat_fabric.testing import sample_trial_df

registry = build_registry([register])
spec = registry.pipeline("exploratory_analysis")
inputs = PipelineInputs.from_values({"data": sample_trial_df()}, registry.types)
plan = parse_plan(
    spec.instantiate({"features": ["nitrogen", "phosphorus", "potassium", "ph"], "k": 3}), registry, inputs
)
report = PipelineExecutor(registry).run(plan, inputs)
assert report.ok, [o.error for o in report.outcomes if o.error]
print(report.by_id("pca").result["cumulative_variance"])  # variance kept by 1, 2, ... components
print(report.by_id("clusters").result["k"])  # 3
