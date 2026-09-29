"""Hierarchical agents: tree validation, delegation, self-correction, budgets, fallbacks, memory, integrations."""

import json
from pathlib import Path

import pytest

from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.errors import AgentConfigError, DependencyError, ErrorDetail
from agent_fabric.llm import ScriptedBackend
from agent_fabric.memory import InMemoryMemory
from agent_fabric.report import render_markdown
from stat_fabric.schemas import Review

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "How do nitrogen treatments affect yield and what do the field notes say?"


def tree(**overrides) -> dict:
    agents = {
        "lead": {"kind": "supervisor", "strategy": "router", "sub_agents": ["stats_team", "digest"],
                 "role": "Research lead", "goal": "answer research questions"},
        "stats_team": {"kind": "supervisor", "strategy": "sequential", "synthesize": False,
                       "sub_agents": ["statistician", "reviewer"], "role": "Stats team", "goal": "run statistics"},
        "statistician": {"kind": "planner", "backend": "stats_rules", "domains": ["statistics"], "inputs": ["data"],
                         "role": "Statistician", "goal": "plan and run analyses",
                         "options": {"hints": {"response": "yield_t_ha", "factors": ["treatment"],
                                               "features": ["nitrogen", "phosphorus", "potassium", "ph"]}}},
        "reviewer": {"kind": "llm", "role": "Reviewer", "goal": "review the statistics"},
        "digest": {"kind": "pipeline", "pipeline": "document_digest", "inputs": ["notes"],
                   "role": "Digester", "goal": "digest field notes"},
    }
    for k, v in overrides.items():
        if v is None:
            agents.pop(k, None)
        else:
            agents[k] = {**agents.get(k, {}), **v}
    return {"root": "lead", "agents": agents}


ROUTE_BAD = {"delegations": [{"id": "d1", "agent": "stats", "instruction": "analyse yield", "inputs": ["dta"]}]}
ROUTE_OK = {"rationale": "split by data type", "delegations": [
    {"id": "d1", "agent": "stats_team", "instruction": "analyse yield vs treatments", "inputs": ["data"]},
    {"id": "d2", "agent": "digest", "instruction": "digest the field notes", "inputs": ["notes"]}]}


def make(registry, cfg: dict, replies=(), **kw) -> tuple[AgentFabric, ScriptedBackend]:
    backend = ScriptedBackend(list(replies))
    fabric = AgentFabric(registry, AgentsConfig.from_dict(cfg), backend=backend, **kw)
    fabric.register_schema("Review", Review)
    return fabric, backend


def errors_of(registry, cfg) -> dict:
    fabric, _ = make(registry, cfg)
    return {(".".join(map(str, d.loc)), d.type): d for d in fabric.validate()}


# ------------------------------------------------------------------ tree validation

def test_valid_tree_and_yaml_config(registry):
    assert errors_of(registry, tree()) == {}
    fabric = AgentFabric(registry, AgentsConfig.load(ROOT / "config"))
    fabric.register_schema("Review", Review)
    assert fabric.validate() == []


def test_tree_errors_are_located_with_hints(registry):
    e = errors_of(registry, tree(
        lead={"sub_agents": ["stats_tem", "digest", "lead"]},
        reviewer={"sub_agents": ["digest"]},
        digest={"pipeline": "document_digets"},
        statistician={"backend": "stat_rules", "domains": ["statistcs"]},
    ))
    assert "stats_team" in e[("agents.lead.sub_agents.0", "unknown_agent")].hint
    assert ("agents.lead.sub_agents.2", "self_reference") in e
    assert ("agents.reviewer.sub_agents", "sub_agents_not_allowed") in e
    assert "document_digest" in e[("agents.digest.pipeline", "unknown_pipeline")].hint
    assert "stats_rules" in e[("agents.statistician.backend", "unknown_backend")].hint


def test_cycle_and_depth(registry):
    e = errors_of(registry, tree(stats_team={"sub_agents": ["statistician", "loop"]},
                                 loop={"kind": "supervisor", "sub_agents": ["stats_team"], "role": "r", "goal": "g"}))
    assert any(t == "cycle" for _, t in e)
    deep = tree()
    deep["budget"] = {"max_depth": 1}
    assert any(t == "too_deep" for _, t in errors_of(registry, deep))


def test_bad_names_and_unknown_root():
    with pytest.raises(AgentConfigError):
        AgentsConfig.from_dict({"root": "nope", "agents": {"A-b": {"kind": "llm", "role": "r", "goal": "g"}}})


def test_build_refuses_invalid_tree(registry):
    fabric, _ = make(registry, tree(lead={"sub_agents": []}))
    with pytest.raises(AgentConfigError) as ei:
        fabric.run(QUESTION, {})
    assert ei.value.details[0].type == "no_sub_agents"


# ------------------------------------------------------------------ running trees

def test_router_self_corrects_and_runs_three_levels(registry, df, note):
    fabric, backend = make(registry, tree(), [
        json.dumps(ROUTE_BAD), json.dumps(ROUTE_OK),
        "The model is plausible; residual checks look acceptable.",       # reviewer
        "Treatments raise yield; notes stress nitrogen and wheat.",       # lead synthesis
    ])
    rep = fabric.run(QUESTION, {"data": df, "notes": note}, session_id="s1")
    r = rep.result
    assert rep.ok, r.tree()
    assert [c.agent for c in r.children] == ["stats_team", "digest"]
    assert [c.agent for c in r.find("stats_team").children] == ["statistician", "reviewer"]
    assert r.find("statistician").output["planner"] == "stats_rules"
    feedback = backend.calls[1]["messages"][-1]["content"]
    assert "unknown_agent" in feedback and "stats_team" in feedback and "unknown_key" in feedback
    # sequential team passes the planner's output to the reviewer
    assert "lead/stats_team/statistician" in backend.calls[2]["messages"][1]["content"]
    paths = {e.path for e in rep.trace}
    assert "lead/stats_team/statistician" in paths and "lead/digest" in paths
    assert rep.usage == {"agent_runs": 5, "delegations": 4, "llm_calls": 4}
    assert "lead/digest.terms" in rep.blackboard
    md = render_markdown(rep)
    assert "- lead [supervisor] ok" in md and "| lead | llm_call |" in md


def test_delegation_outputs_and_dependencies(registry, df, note):
    route = {"delegations": [
        {"id": "a", "agent": "digest", "instruction": "digest notes", "inputs": ["missing_but_valid_key"]},
        {"id": "b", "agent": "stats_team", "instruction": "use digest", "inputs": ["data", "@a"]}]}
    fabric, _ = make(registry, tree(lead={"synthesize": False}), [json.dumps(route)])
    rep = fabric.run(QUESTION, {"data": df, "notes": note, "missing_but_valid_key": 42})
    r = rep.result
    assert r.find("digest").status == "failed"          # 42 is not text -> pipeline input missing
    assert r.find("stats_team").status == "skipped"     # depends on failed delegation
    assert r.status == "failed" and r.error.category.value == "dependency"


def test_structured_output_with_grounding(registry, df, note):
    cfg = tree(reviewer={"output_schema": "Review", "options": {"check_grounding": True}}, lead={"synthesize": False})
    route = {"delegations": [{"id": "d1", "agent": "stats_team", "instruction": "analyse", "inputs": ["data"]}]}
    hallucinated = {"verdict": "sound", "summary": "R2 is 0.987654", "issues": []}
    grounded = {"verdict": "caveats", "summary": "Model is useful but check residuals", "issues": ["autocorrelation"]}
    fabric, backend = make(registry, cfg, [json.dumps(route), json.dumps(hallucinated), json.dumps(grounded)])
    rep = fabric.run(QUESTION, {"data": df, "notes": note})
    out = rep.result.find("reviewer").output
    assert out == grounded
    assert "ungrounded_number" in backend.calls[2]["messages"][-1]["content"]


def test_budget_stops_the_tree(registry, df, note):
    cfg = tree()
    cfg["budget"] = {"max_llm_calls": 1}
    fabric, backend = make(registry, cfg, [json.dumps(ROUTE_OK), "never used"])
    rep = fabric.run(QUESTION, {"data": df, "notes": note})
    reviewer = rep.result.find("reviewer")
    assert reviewer.status == "failed" and reviewer.error.category.value == "budget"
    assert rep.result.find("digest").status == "skipped"  # later delegation not started
    assert any("budget exhausted" in n for n in rep.result.notes)  # no synthesis call
    assert len(backend.calls) == 1 and rep.usage["llm_calls"] == 2  # refused call counted, never sent


class DownBackend:
    def complete(self, *a, **k):
        raise DependencyError("LiteLLM proxy is unreachable", [ErrorDetail(type="connection_error", msg="refused")])


def test_fallbacks_when_proxy_is_down(registry, df, note):
    cfg = tree(lead={"fallback": "rules"}, reviewer=None,
               stats_team={"sub_agents": ["statistician"]},
               statistician={"backend": "fabric", "fallback": "stats_rules"})
    fabric = AgentFabric(registry, AgentsConfig.from_dict(cfg), backend=DownBackend())
    rep = fabric.run(QUESTION, {"data": df, "notes": note})
    assert rep.ok, rep.result.tree()
    assert rep.result.output["strategy"] == "sequential"                       # router -> rules
    assert any("fell back" in n for n in rep.result.notes)
    st = rep.result.find("statistician")
    assert st.output["planner"] == "stats_rules" and any("fell back" in n for n in st.notes)
    assert any(e.event == "fallback" for e in rep.trace)


def test_function_agent_and_custom_kind(registry, df):
    @AgentFabric.builder("echo", "fabric")
    def _echo(f, name, spec, children):
        from agent_fabric.agents import LLMWorkerAgent

        class Echo(LLMWorkerAgent):
            def _run(self, task, ctx, path, depth):
                return self.result(path, "ok", output={"echo": task.instruction}, summary=task.instruction,
                                   artifacts=[ctx.put(path, {"echo": task.instruction})])
        return Echo(name, spec, f)

    cfg = {"root": "team", "agents": {
        "team": {"kind": "supervisor", "backend": "rules", "sub_agents": ["rows", "echo"], "role": "t", "goal": "g"},
        "rows": {"kind": "function", "function": "count_rows", "inputs": ["data"], "role": "counter", "goal": "count"},
        "echo": {"kind": "echo", "role": "e", "goal": "echo"}}}
    fabric, backend = make(registry, cfg)
    fabric.register_function("count_rows", lambda task, inputs: {"summary": f"{len(inputs['data'])} rows"})
    rep = fabric.run("count and echo", {"data": df})
    assert rep.ok and rep.result.find("rows").summary == "120 rows"
    assert rep.result.find("echo").output == {"echo": "count and echo"}
    assert backend.calls == []  # rules supervisor + function + custom kind: no LLM


def test_memory_is_namespaced_per_agent(registry, df, note):
    mem = InMemoryMemory()
    replies = [json.dumps(ROUTE_OK), "r1", "s1", json.dumps(ROUTE_OK), "r2", "s2"]
    fabric, backend = make(registry, tree(), replies, memory=mem)
    fabric.run("first question about yield", {"data": df, "notes": note}, session_id="trial")
    fabric.run("second question", {"data": df, "notes": note}, session_id="trial")
    assert "trial/lead/stats_team/statistician" in mem.sessions()
    second_router_prompt = backend.calls[3]["messages"][1]["content"]
    assert "Previous runs of this team" in second_router_prompt and "first question about yield" in second_router_prompt


def test_pydantic_ai_supervisor_delegates_via_tools(registry, df, note):
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    calls = []

    def fn(messages, info):
        calls.append(messages)
        n = len(calls)
        if n == 1:
            return ModelResponse(parts=[ToolCallPart("delegate", {"agent_name": "digst", "instruction": "digest"})])
        if n == 2:
            return ModelResponse(parts=[ToolCallPart("delegate", {"agent_name": "digest", "instruction": "digest notes",
                                                                  "inputs": ["notes"]})])
        return ModelResponse(parts=[TextPart("The notes focus on nitrogen.")])

    cfg = tree(lead={"backend": "pydantic_ai", "options": {"model_object": FunctionModel(fn)}})
    fabric, _ = make(registry, cfg)
    rep = fabric.run(QUESTION, {"data": df, "notes": note})
    assert rep.ok and [c.agent for c in rep.result.children] == ["digest"]
    assert "digest" in str(calls[1][-1])  # ModelRetry suggested the right name
    assert rep.result.output["answer"]["text"] == "The notes focus on nitrogen."
    assert rep.usage["llm_calls"] == 3


def test_crewai_hierarchical_mapping(registry, df, note):
    pytest.importorskip("crewai")
    from agent_fabric.integrations.crewai import build_crew

    fabric, backend = make(registry, tree(stats_team={"sub_agents": ["statistician"]}, reviewer=None))
    crew, ctx = build_crew(fabric, QUESTION, {"data": df, "notes": note})
    assert crew.process.value == "hierarchical" and len(crew.agents) == 2
    digest_tool = next(a for a in crew.agents if a.role == "Digester").tools[0]
    out = digest_tool.run(instruction="digest the notes")
    assert out.startswith("[ok]") and "lead/digest.terms" in ctx.blackboard
    assert backend.calls == []


def test_stats_facade(df):
    from stat_fabric.app import StatisticalAnalysisFabric

    rep = StatisticalAnalysisFabric(backend=DownBackend()).analyze(df, "What drives yield?")
    assert rep.ok and rep.result.output["planner"] == "stats_rules"


def test_langchain_memory_backs_the_tree(registry, df, note):
    pytest.importorskip("langchain_core")
    from agent_fabric.memory import LangChainMemory

    mem = LangChainMemory()
    fabric, _ = make(registry, tree(lead={"backend": "rules"}, reviewer=None, stats_team={"sub_agents": ["statistician"]}),
                     memory=mem)
    fabric.run("first run", {"data": df, "notes": note}, session_id="lc")
    runs = mem.recent_runs("lc/lead/digest")
    assert runs and runs[0].agent == "lead/digest"
    assert mem.history("lc/lead")[0] == ("user", "first run")
    assert len(mem.as_langchain_history("lc/lead").messages) == 3  # human, ai, run summary
