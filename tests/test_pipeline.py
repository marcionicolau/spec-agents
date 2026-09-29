"""Generic pipelines: bindings, references, validation, nesting and execution policies."""

import json

import pytest

from agent_fabric.errors import ParamsValidationError, PlanValidationError
from agent_fabric.executor import PipelineExecutor, StepStatus
from agent_fabric.pipeline import PipelineInputs, parse_plan


def details(exc):
    return {(".".join(map(str, d.loc)), d.type): d for d in exc.details}


def test_full_plan_runs_and_exposes_outputs(registry, pin, good_plan):
    plan = parse_plan(good_plan, registry, pin)
    rep = PipelineExecutor(registry).run(plan, pin)
    assert rep.ok, [o.error for o in rep.outcomes if o.error]
    assert rep.by_id("clusters").bindings == {"matrix": "pca.scores", "data": "$inputs.data"}
    assert rep.by_id("clusters").result["space"] == "matrix"
    labels = rep.output_values()["labels"]
    assert len(labels) == 120
    json.dumps(rep.model_dump(mode="json"))  # serialisable, NaN -> null


def test_auto_bind_by_type_when_names_differ(registry, df):
    pin = PipelineInputs.from_values({"trial": df}, registry.types)
    plan = parse_plan({"objective": "auto bind", "steps": [{"id": "s", "component": "summary"}]}, registry, pin)
    assert PipelineExecutor(registry).run(plan, pin).by_id("s").bindings == {"data": "$inputs.trial"}


def test_plan_collects_all_errors_with_locations(registry, pin):
    bad = {"objective": "many errors", "steps": [
        {"id": "s", "component": "sumary"},
        {"id": "lm", "component": "linear_model", "params": {"response": "yeld", "predictors": ["nitrogen"]}},
        {"id": "p", "component": "pca", "params": {"features": ["nitrogen", "ph"]}},
        {"id": "cl", "component": "clustering", "inputs": {"matrix": "p.score"}},
        {"id": "k", "component": "keywords", "inputs": {"txt": "$inputs.data"}},
    ]}
    with pytest.raises(PlanValidationError) as ei:
        parse_plan(bad, registry, pin)
    d = details(ei.value)
    assert "summary" in d[("steps.0.component", "unknown_component")].hint
    assert "yield_t_ha" in d[("steps.1.params.response", "column_not_found")].hint
    assert "scores" in d[("steps.3.inputs.matrix", "unknown_output")].hint
    assert ("steps.4.inputs.txt", "unknown_port") in d
    assert ("steps.4.inputs.text", "port_unbound") in d  # keywords needs text; data is a dataframe
    fb = json.loads(ei.value.report.to_llm_feedback())
    assert fb["error_category"] == "plan"


def test_type_mismatch(registry, pin):
    with pytest.raises(PlanValidationError) as ei:
        parse_plan({"objective": "types", "steps": [
            {"id": "p", "component": "pca", "params": {"features": ["nitrogen", "ph"]}},
            {"id": "k", "component": "keywords", "inputs": {"text": "p.scores"}}]}, registry, pin)
    assert ("steps.1.inputs.text", "type_mismatch") in details(ei.value)


def test_clustering_source_rules(registry, pin):
    with pytest.raises(PlanValidationError) as ei:
        parse_plan({"objective": "no source", "steps": [{"id": "c", "component": "clustering"}]}, registry, pin)
    assert ("steps.0.inputs.matrix", "no_source") in details(ei.value)


def test_cycles_via_references(registry, pin):
    with pytest.raises(PlanValidationError) as ei:
        parse_plan({"objective": "cycle", "steps": [
            {"id": "a", "component": "summary", "depends_on": ["b"]},
            {"id": "b", "component": "clustering", "inputs": {"matrix": "a.result"}}]}, registry, pin)
    assert "cycle" in ei.value.details[0].msg


def test_param_refs_rejected_in_plans(registry, pin):
    with pytest.raises(PlanValidationError) as ei:
        parse_plan({"objective": "params", "steps": [{"id": "s", "component": "summary", "inputs": {"data": "$params.x"}}]},
                   registry, pin)
    assert ("steps.0.inputs.data", "param_ref_not_allowed") in details(ei.value)


def test_pipeline_spec_instantiate(registry):
    spec = registry.pipeline("exploratory_analysis")
    raw = spec.instantiate({"features": ["nitrogen", "ph"]})
    assert raw["steps"][1]["params"] == {"features": ["nitrogen", "ph"], "variance_threshold": 0.8}
    assert "k" not in raw["steps"][2]["params"]  # None default dropped -> component default
    with pytest.raises(ParamsValidationError) as ei:
        spec.instantiate({"featurs": ["a"]})
    assert {d.type for d in ei.value.details} == {"extra_forbidden", "missing"}


def test_nested_pipelines_three_levels(registry, pin):
    plan = parse_plan({"objective": "nested", "steps": [
        {"id": "study", "component": "full_study", "params": {
            "response": "yield_t_ha", "factors": ["treatment"], "predictors": ["nitrogen", "treatment"],
            "features": ["nitrogen", "phosphorus", "potassium"]}}],
        "outputs": {"labels": "study.labels"}}, registry, pin)
    rep = PipelineExecutor(registry).run(plan, pin)
    o = rep.by_id("study")
    assert o.status == StepStatus.OK
    assert o.result["steps"] == {"experiment": "ok", "profile": "ok"}
    assert o.result["step_results"]["profile"]["steps"] == {"summary": "ok", "pca": "ok", "clusters": "ok"}
    assert len(rep.output_values()["labels"]) == 120


def test_nested_failure_is_located(registry, df):
    pin = PipelineInputs.from_values({"data": df.head(8)}, registry.types)
    plan = parse_plan({"objective": "nested fail", "steps": [
        {"id": "ex", "component": "exploratory_analysis", "params": {"features": ["nitrogen", "ph", "rainfall"]}}]},
        registry, pin)
    o = PipelineExecutor(registry).run(plan, pin).by_id("ex")
    assert o.status == StepStatus.FAILED
    assert o.error.details[0].loc[:2] == ("pipeline", "clusters")


def test_failed_step_skips_dependents(registry, df):
    pin = PipelineInputs.from_values({"data": df.head(8)}, registry.types)
    plan = parse_plan({"objective": "skip", "steps": [
        {"id": "p", "component": "pca", "params": {"features": ["nitrogen", "ph"]}},
        {"id": "c", "component": "clustering", "inputs": {"matrix": "p.scores"}},
        {"id": "after", "component": "summary", "depends_on": ["c"]},
        {"id": "s", "component": "summary"}]}, registry)  # no inputs: static checks deferred to runtime
    rep = PipelineExecutor(registry).run(plan, pin)
    assert [rep.by_id(i).status for i in ("p", "c", "after", "s")] == [
        StepStatus.OK, StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.OK]
    with pytest.raises(PlanValidationError):  # with inputs, the same problem is caught before running
        parse_plan(plan, registry, pin)


def test_fail_fast(registry, pin):
    plan = parse_plan({"objective": "fail fast", "steps": [
        {"id": "bad", "component": "linear_model", "params": {"response": "missing", "predictors": ["nitrogen"]}},
        {"id": "after", "component": "summary", "depends_on": ["bad"]}]}, registry)  # no inputs -> runtime failure
    rep = PipelineExecutor(registry, fail_policy="fail_fast").run(plan, pin)
    assert rep.by_id("bad").status == StepStatus.FAILED and rep.by_id("after").status == StepStatus.SKIPPED
    assert rep.by_id("after").error.category.value == "dependency"


def test_text_pipeline(registry, note):
    pin = PipelineInputs.from_values({"text": note}, registry.types)
    raw = registry.pipeline("document_digest").instantiate({"top_k": 4})
    rep = PipelineExecutor(registry).run(parse_plan(raw, registry, pin), pin)
    assert rep.ok and len(rep.output_values()["terms"]) == 4
