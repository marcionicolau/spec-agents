"""Self-correction loop, planners (fabric / PydanticAI / DSPy / template), grounding, param repair."""

import json

import pytest

from agent_fabric.errors import LLMOutputError, PlanValidationError
from agent_fabric.executor import PipelineExecutor, StepStatus
from agent_fabric.llm import (
    CorrectionExhausted,
    LLMInterpreter,
    LLMParamRepairer,
    LLMPlanner,
    LLMSettings,
    ScriptedBackend,
    TemplatePlanner,
    extract_json,
)
from agent_fabric.llm.interpreter import Interpretation, grounding_errors
from agent_fabric.pipeline import parse_plan

S = LLMSettings(max_correction_attempts=3)


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    'Sure!\n```json\n{"a": 1}\n```\nHope it helps',
    'prefix {"a": 1, } suffix',
    '{"a": 1} and then {"b": 2}',
    '{"s": "brace } inside \\" string", "a": 1}',
])
def test_extract_json_tolerant(text):
    assert extract_json(text)["a"] == 1


@pytest.mark.parametrize("text,kind", [("", "empty_output"), ("no json", "no_json"), ('{"a": 1', "json_decode")])
def test_extract_json_errors_typed(text, kind):
    with pytest.raises(LLMOutputError) as ei:
        extract_json(text)
    assert ei.value.details[0].type == kind


def test_planner_self_corrects(registry, pin, good_plan):
    bad = json.loads(json.dumps(good_plan))
    bad["steps"][1]["params"]["response"] = "yield"
    bad["steps"][5]["inputs"] = {"matrix": "pca.score"}
    backend = ScriptedBackend(["I'd run a regression.", "```json\n" + json.dumps(bad) + "\n```", json.dumps(good_plan)])
    out = LLMPlanner(backend, registry, S, domains=["statistics"]).plan("yield", pin)
    assert out.attempts == 3 and [r.category.value for r in out.rejected] == ["llm_output", "plan"]
    assert {d.type for d in out.rejected[1].details} == {"column_not_found", "unknown_output"}
    third = backend.calls[2]["messages"]
    assert len(third) == 4 and "yield_t_ha" in third[-1]["content"]  # context does not grow
    assert "keywords" not in backend.calls[0]["messages"][1]["content"]  # catalogue scoped to domain


def test_planner_domain_scope_enforced(registry, pin):
    plan = {"objective": "out of scope", "steps": [{"id": "k", "component": "keywords", "inputs": {"text": "$inputs.data"}}]}
    backend = ScriptedBackend([json.dumps(plan)] * 2)
    with pytest.raises(CorrectionExhausted) as ei:
        LLMPlanner(backend, registry, LLMSettings(max_correction_attempts=2), domains=["statistics"]).plan("x", pin)
    assert any(d.type in ("component_out_of_scope", "type_mismatch", "port_unbound") for d in ei.value.details)


def test_template_planner(registry, pin):
    out = TemplatePlanner(registry, "experiment_analysis",
                          {"response": "yield_t_ha", "factors": ["treatment"], "predictors": ["nitrogen"]}).plan("trial", pin)
    assert [s.id for s in out.plan.steps] == ["summary", "anova", "model"]
    with pytest.raises(PlanValidationError):
        TemplatePlanner(registry, "experiment_analysis",
                        {"response": "yield", "factors": ["treatment"], "predictors": ["nitrogen"]}).plan("trial", pin)


def _outcome(registry, pin, good_plan, step):
    return PipelineExecutor(registry).run(parse_plan(good_plan, registry, pin), pin).by_id(step)


def test_interpreter_grounding_loop(registry, pin, good_plan):
    o = _outcome(registry, pin, good_plan, "aov")
    f_val = round(next(r for r in o.result["table"] if r["source"] == "treatment")["f_value"], 1)
    bad = {"headline": "Treatments differ", "findings": ["F = 987.65"], "caveats": [], "confidence": "high"}
    good = {"headline": "Treatments differ", "findings": [f"F = {f_val}"], "caveats": [], "confidence": "high"}
    backend = ScriptedBackend([json.dumps(bad), json.dumps(good)])
    it = LLMInterpreter(backend, S).interpret(o, "yield", registry)
    assert it.findings == good["findings"]
    assert "ungrounded_number" in backend.calls[1]["messages"][-1]["content"]


def test_grounding_accepts_percent_and_rounding(registry, pin, good_plan):
    o = _outcome(registry, pin, good_plan, "pca")
    pc1 = o.result["components"]["PC1"]["explained_variance_ratio"]
    it = Interpretation(step_id="pca", headline="PCA", confidence="high", findings=[f"PC1 {pc1:.1%}", f"ratio {pc1:.3f}"])
    assert grounding_errors(it, o.result) == []


def test_param_repair(registry, pin):
    plan = parse_plan({"objective": "repair", "steps": [
        {"id": "lm", "component": "linear_model", "params": {"response": "Yield", "predictors": ["nitrogen"]}}]}, registry)
    backend = ScriptedBackend(['{"params": {"response": "yield", "predictors": ["nitrogen"]}}',
                               '{"params": {"response": "yield_t_ha", "predictors": ["nitrogen"]}}'])
    o = PipelineExecutor(registry, repairer=LLMParamRepairer(backend, registry, S)).run(plan, pin).by_id("lm")
    assert o.status == StepStatus.REPAIRED and o.params["response"] == "yield_t_ha"
    assert o.repair_history[0].details[0].type == "column_not_found"


def test_pydantic_ai_planner(registry, pin, good_plan):
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    from agent_fabric.llm import PydanticAIPlanner

    bad = json.loads(json.dumps(good_plan))
    bad["steps"][2]["params"]["factors"] = ["nitrogen"]
    replies = iter([json.dumps(bad), json.dumps(good_plan)])
    seen = []

    def fn(messages, info):
        seen.append(messages)
        return ModelResponse(parts=[TextPart(next(replies))])

    out = PydanticAIPlanner(registry, S, model=FunctionModel(fn), domains=["statistics"]).plan("yield", pin)
    assert out.attempts == 2 and out.rejected[0].details[0].type == "wrong_dtype"
    assert "wrong_dtype" in str(seen[-1][-1])


def test_dspy_planner(registry, pin, good_plan):
    dspy = pytest.importorskip("dspy")
    from dspy.utils.dummies import DummyLM

    from agent_fabric.integrations.dspy import DSPyPlanner, plan_metric

    bad = json.loads(json.dumps(good_plan))
    bad["steps"][0]["component"] = "describe"
    dspy.configure(lm=DummyLM([{"reasoning": "r", "plan": json.dumps(bad)}, {"reasoning": "r", "plan": json.dumps(good_plan)}]))
    out = DSPyPlanner(registry, domains=["statistics"]).plan("yield", pin)
    assert out.planner == "dspy" and out.attempts == 2 and out.rejected[0].details[0].type == "unknown_component"
    pred = dspy.Prediction(plan=out.plan, rejected=out.rejected, valid=True)
    assert plan_metric(dspy.Example(expected_components=["summary", "pca"]), pred) == 0.9
