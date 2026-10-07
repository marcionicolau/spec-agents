"""Text pack on its own: no pandas, no other domain pack."""

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor, StepStatus
from agent_fabric.llm import ScriptedBackend
from agent_fabric.pipeline import parse_plan
from agent_fabric.testing import run_component
from text_pack import register

NOTE = "Nitrogen improved grain filling. Nitrogen uptake limited phosphorus uptake; rainfall in October mattered."


def make_registry():
    return build_registry([register])


def test_registers_components_and_pipeline():
    reg = make_registry()
    assert set(reg.names(["text"])) == {
        "text_stats",
        "keywords",
        "summarize_text",
        "document_digest",
        "document_summary",
    }
    assert {"document_digest", "document_summary"} <= set(reg.pipelines())


def test_keywords_rank_repeated_terms_first():
    res, _ = run_component(make_registry(), "keywords", {"top_k": 3}, text=NOTE)
    assert [k.term for k in res.keywords][:1] == ["nitrogen"]


def test_document_digest_pipeline_runs():
    reg = make_registry()
    plan = parse_plan(reg.pipeline("document_digest").instantiate({}), reg)
    rep = PipelineExecutor(reg).run(plan, {"text": NOTE})
    assert rep.ok


def test_document_summary_pipeline_runs():
    reg = make_registry()
    plan = parse_plan(reg.pipeline("document_summary").instantiate({}), reg)
    rep = PipelineExecutor(reg, llm=ScriptedBackend(['{"summary": "Nitrogen improved grain filling."}'])).run(
        plan, {"text": NOTE}
    )
    assert rep.ok and rep.output_values()["summary"] == "Nitrogen improved grain filling."


def test_document_summary_step_needs_llm():
    reg = make_registry()
    plan = parse_plan(reg.pipeline("document_summary").instantiate({}), reg)
    rep = PipelineExecutor(reg).run(plan, {"text": NOTE})
    assert not rep.ok and rep.by_id("sum").status == StepStatus.FAILED
