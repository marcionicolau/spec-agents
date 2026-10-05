"""Run the text pack's ``document_digest`` pipeline: deterministic components, no model."""

from __future__ import annotations

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import parse_plan
from text_pack import register

registry = build_registry([register])  # components, pipelines and artifact types of the text domain
plan = parse_plan(registry.pipeline("document_digest").instantiate({"top_k": 3}), registry)
report = PipelineExecutor(registry).run(
    plan, {"text": "Nitrogen improved grain filling. Nitrogen uptake limited phosphorus uptake."}
)
assert report.ok
print([o.step_id for o in report.outcomes])  # ['stats', 'kw']
print(report.artifacts.get("kw.terms"))  # ['nitrogen', 'uptake', 'improved']
