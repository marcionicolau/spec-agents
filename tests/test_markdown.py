"""SKILL.md / AGENT.md: loading, equivalence with YAML, guidance usage, lint and evals."""

import json
from pathlib import Path

import pytest

from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.errors import AgentConfigError, SpecError
from agent_fabric.evals import PlannerCase, evaluate_planner, load_cases, score_plan
from agent_fabric.executor import PipelineExecutor
from agent_fabric.lint import lint_agents, lint_skills, run
from agent_fabric.llm import LLMInterpreter, LLMParamRepairer, LLMPlanner, LLMSettings, ScriptedBackend, TemplatePlanner
from agent_fabric.markdown import read_markdown, split_sections
from agent_fabric.pipeline import parse_plan
from agent_fabric.registry import Registry
from agent_fabric.spec import load_spec
from stat_fabric.schemas import Review

ROOT = Path(__file__).resolve().parents[1]
S = LLMSettings(max_correction_attempts=3)

SKILL = """---
name: {name}
version: 1.0.0
domain: demo
description: Demo component for tests.
params:
  top_k: {{description: how many}}
inputs:
  text: {{type: text}}
---
# Demo

## When to use
Use it for demos. Second sentence of the first paragraph.

Second paragraph is not part of the catalogue.

## Avoid when
Never in production.

## Interpreting
Look at `top_k` and `unknown_thing`.

## Common mistakes
Setting `top_k` to zero. See [details](references/more.md).
"""


def write_skill(root: Path, name: str = "demo", folder: str | None = None) -> Path:
    p = root / (folder or name) / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(SKILL.format(name=name))
    return p


# ------------------------------------------------------------------ markdown & specs


def test_sections_and_aliases():
    s = split_sections("# T\n\n## When to use\nA\n\n## Avoid when\nB\n## Pitfalls ##\nC")
    assert s == {"when to use": "A", "when not to use": "B", "common mistakes": "C"}


def test_frontmatter_required(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("# no frontmatter")
    with pytest.raises(SpecError) as ei:
        read_markdown(p)
    assert ei.value.details[0].type == "missing_frontmatter"
    p.write_text("---\nname: [unclosed\n---\nbody")
    with pytest.raises(SpecError) as ei:
        read_markdown(p)
    assert ei.value.details[0].type == "yaml_error"


def test_skill_guidance_accessors(tmp_path):
    spec = load_spec(write_skill(tmp_path))
    assert spec.title == "Demo"
    assert spec.when_to_use == "Use it for demos. Second sentence of the first paragraph."
    assert spec.avoid_when == "Never in production."
    assert "unknown_thing" in spec.interpretation_guide
    assert spec.common_mistakes.startswith("Setting `top_k`")


def test_skill_and_yaml_produce_the_same_contract(tmp_path):
    md = load_spec(write_skill(tmp_path))
    y = tmp_path / "demo.yaml"
    y.write_text(
        "name: demo\nversion: 1.0.0\ndomain: demo\ndescription: Demo component for tests.\ntitle: Demo\n"
        "params: {top_k: {description: how many}}\ninputs: {text: {type: text}}\n"
    )
    legacy = load_spec(y)
    drop = {"guidance", "llm"}
    assert md.model_dump(exclude=drop) == legacy.model_dump(exclude=drop)
    assert legacy.when_to_use == legacy.description  # YAML without hints falls back to the description


def test_folder_must_match_name_and_errors_are_aggregated(tmp_path):
    write_skill(tmp_path, "demo", folder="other")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "SKILL.md").write_text("no frontmatter")
    from agent_fabric.spec import load_spec_dir

    with pytest.raises(SpecError) as ei:
        load_spec_dir(tmp_path)
    assert {d.type for d in ei.value.details} == {"name_mismatch", "missing_frontmatter"}


def test_references_loaded_on_demand(registry):
    g = registry.spec("pca").guidance
    assert g.references == ["interpretation_examples.md"]
    assert "acidity/potassium contrast" in g.reference("interpretation_examples.md")
    assert "acidity/potassium contrast" not in g.body  # never injected unless asked for
    assert registry.guidance("pca", "interpreting").startswith("- `cumulative_variance`")


def test_catalogue_uses_skill_guidance(registry):
    cat = {c["name"]: c for c in registry.catalog(["statistics"])}
    assert cat["pca"]["when_to_use"].startswith("Several correlated numeric variables")
    assert cat["anova"]["avoid_when"].startswith("The grouping variable is continuous")
    assert cat["exploratory_analysis"]["when_to_use"].startswith("Profile observations")  # pipelines too


# ------------------------------------------------------------------ guidance reaches the prompts


def test_interpreter_prompt_contains_interpreting_section(registry, pin, good_plan):
    o = PipelineExecutor(registry).run(parse_plan(good_plan, registry, pin), pin).by_id("pca")
    backend = ScriptedBackend([json.dumps({"headline": "PCA done", "findings": ["ok"], "confidence": "high"})])
    LLMInterpreter(backend, S).interpret(o, "profile soils", registry)
    assert "Name each component by its `top_features`" in backend.calls[0]["messages"][1]["content"]


def test_repair_and_planner_feedback_include_common_mistakes(registry, pin, good_plan):
    plan = parse_plan(
        {
            "objective": "repair",
            "steps": [
                {"id": "lm", "component": "linear_model", "params": {"response": "Yield", "predictors": ["nitrogen"]}}
            ],
        },
        registry,
    )
    backend = ScriptedBackend(['{"params": {"response": "yield_t_ha", "predictors": ["nitrogen"]}}'])
    PipelineExecutor(registry, repairer=LLMParamRepairer(backend, registry, S)).run(plan, pin)
    assert "Known pitfalls for this component" in backend.calls[0]["messages"][1]["content"]

    bad = json.loads(json.dumps(good_plan))
    bad["steps"][1]["params"]["response"] = "yield"
    backend = ScriptedBackend([json.dumps(bad), json.dumps(good_plan)])
    LLMPlanner(backend, registry, S, ["statistics"]).plan("yield", pin)
    feedback = backend.calls[1]["messages"][-1]["content"]
    assert "Known pitfalls of the components involved" in feedback and "[linear_model]" in feedback


# ------------------------------------------------------------------ AGENT.md


def test_agent_dir_loads_and_bodies_become_system_prompts(registry, df, note):
    cfg = AgentsConfig.load(ROOT / "config")
    assert cfg.root == "research_lead" and len(cfg.agents) == 6
    lead = cfg.agents["research_lead"]
    assert lead.source.endswith("research_lead/AGENT.md") and "Break the question down" in lead.instructions
    assert cfg.agents["stats_team"].card.startswith("Statistical analysis of tabular")
    route = {"delegations": [{"id": "n", "agent": "notes_digest", "instruction": "digest notes", "inputs": ["notes"]}]}
    backend = ScriptedBackend([json.dumps(route), "The notes mention nitrogen."])
    fabric = AgentFabric(registry, cfg, backend=backend)
    fabric.register_schema("Review", Review)
    rep = fabric.run("What do the notes say?", {"data": df, "notes": note})
    assert rep.ok
    system = backend.calls[0]["messages"][0]["content"]
    assert system.startswith("You are Research lead for agronomic field trials.")
    assert "Break the question down" in system and "Sub-agents available" in system


def _agent(root: Path, folder: str, text: str) -> None:
    p = root / "agents" / folder / "AGENT.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_agent_dir_errors_are_aggregated_with_file_locations(tmp_path):
    (tmp_path / "fabric.md").write_text("---\nroot: lead\n---\n")
    _agent(tmp_path, "lead", "---\nname: boss\nkind: supervisor\nsub_agents: [w]\n---\nLead.")
    _agent(tmp_path, "w", "---\nkind: llm\ninstructions: nope\n---\nWorker.")
    _agent(tmp_path, "empty", "---\nkind: llm\n---\n")
    with pytest.raises(AgentConfigError) as ei:
        AgentsConfig.load(tmp_path)
    got = {(d.loc[0], d.type) for d in ei.value.details}
    assert ("agents/lead/AGENT.md", "name_mismatch") in got
    assert ("agents/w/AGENT.md", "derived_field") in got
    assert ("agents/empty/AGENT.md", "value_error") in got  # no goal / description / instructions


def test_legacy_yaml_config_still_loads(tmp_path):
    y = tmp_path / "agents.yaml"
    y.write_text("root: a\nagents:\n  a: {kind: llm, role: r, goal: g}\n")
    assert AgentsConfig.load(y).agents["a"].goal == "g"


# ------------------------------------------------------------------ lint


def test_lint_skill_drift(tmp_path):
    from agent_fabric.component import Component, ComponentParams, ComponentResult

    write_skill(tmp_path)
    reg = Registry()

    class P(ComponentParams):
        top_k: int = 3

    class Demo(Component):
        spec_name, Params, Result = "demo", P, ComponentResult

        def compute(self, inputs, params, ctx):  # pragma: no cover
            return ComponentResult()

    reg.load_domain(tmp_path, [Demo])
    issues = {(i.code, i.severity) for i in lint_skills(reg)}
    assert ("unknown_identifier", "warning") in issues  # `unknown_thing`
    assert ("broken_link", "error") in issues  # references/more.md missing


def test_lint_agents_and_cli(registry, tmp_path, capsys):
    cfg = AgentsConfig.load(ROOT / "config")
    cfg.agents["research_lead"].instructions = "Delegate to `stats_team` and `notes_digest` only."
    fabric = AgentFabric(registry, cfg)
    fabric.register_schema("Review", Review)
    codes = {i.code for i in lint_agents(fabric)}
    assert "undocumented_sub_agent" in codes  # profile_runner never mentioned by the router
    assert (
        run(
            ["stat_fabric.domain:register", "examples.domains.text_pack:register"],
            str(ROOT / "config"),
            strict=True,
            schemas=["stat_fabric.schemas:SCHEMAS"],
        )
        == 0
    )
    assert run(["stat_fabric.domain:register"], str(ROOT / "config")) == 1  # document_digest missing -> error
    assert "unknown_pipeline" in capsys.readouterr().out


# ------------------------------------------------------------------ evals


def test_score_plan():
    assert score_plan(None, 0) == 0.0
    assert score_plan(["summary", "anova"], 0, ["anova"]) == 1.0
    assert score_plan(["summary", "anova"], 2, ["anova", "pca"]) == 0.8
    assert score_plan(["summary", "time_series"], 0, [], ["time_series"]) == 0.7


def test_evaluate_planner(registry, pin, good_plan):
    cases = load_cases(ROOT / "examples" / "evals" / "planner_cases.yaml")
    assert [c.name for c in cases][:2] == ["treatment_effect", "yield_drivers"]
    template = TemplatePlanner(
        registry,
        "experiment_analysis",
        {"response": "yield_t_ha", "factors": ["treatment"], "predictors": ["nitrogen"]},
    )
    rep = evaluate_planner(template, cases[:2], {"trial": pin})
    assert rep.passed and rep.mean_score == 1.0
    llm = LLMPlanner(ScriptedBackend(["not json"] * 3), registry, S)
    rep = evaluate_planner(llm, [PlannerCase(name="x", objective="x", inputs="trial")], {"trial": pin})
    assert not rep.passed and rep.results[0].error.startswith("llm_output")
    assert "✘" in rep.table()


def test_scaffolded_files_load(tmp_path):
    from agent_fabric.scaffold import scaffold
    from agent_fabric.spec import load_spec

    spec = load_spec(scaffold("skill", "my_step", tmp_path, "demo"))
    assert spec.name == "my_step" and spec.guidance.section("common mistakes").startswith("TODO")
    assert load_spec(scaffold("pipeline", "my_flow", tmp_path, "demo")).kind == "pipeline"
    scaffold("agent", "helper", tmp_path, kind="llm")
    (tmp_path / "fabric.md").write_text("---\nroot: helper\n---\n")
    assert AgentsConfig.load(tmp_path).agents["helper"].instructions.startswith("TODO")
    with pytest.raises(FileExistsError):
        scaffold("agent", "helper", tmp_path)
