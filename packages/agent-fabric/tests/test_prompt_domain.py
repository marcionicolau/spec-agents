"""runtime: prompt - code-free domains (SKILL.md only, no Python classes)."""

from pathlib import Path

import pytest

from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.errors import FabricError, SpecError
from agent_fabric.executor import PipelineExecutor, StepStatus
from agent_fabric.llm.backends import LLMSettings, ScriptedBackend
from agent_fabric.pipeline import parse_plan
from agent_fabric.spec import load_spec

NOTES = str(Path(__file__).resolve().parents[3] / "examples" / "notes")
TRANSCRIPT = "We agreed to ship on Friday. Ana owns the release notes."


def notes_registry():
    return build_registry([NOTES + "/skills"])


def run_steps(reg, raw_plan, backend, transcript=TRANSCRIPT):
    plan = parse_plan(raw_plan, reg)
    return PipelineExecutor(reg, llm=backend, llm_settings=LLMSettings()).run(plan, {"transcript": transcript})


# ------------------------------------------------------------------ spec / registration
def test_prompt_spec_parses():
    spec = load_spec(f"{NOTES}/skills/extract_actions/SKILL.md")
    assert spec.runtime == "prompt"
    assert spec.prompt.grounding is True
    assert spec.params["default_owner"].default == "unassigned"


def test_prompt_block_rejected_on_code_runtime(tmp_path):
    f = tmp_path / "x.md"
    f.write_text(
        "---\nname: x\nversion: 1.0.0\ndescription: a thing\nruntime: code\nprompt: {grounding: false}\n---\n# X\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError):
        load_spec(f)


def test_missing_instructions_section(tmp_path):
    d = tmp_path / "skills" / "bare"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: bare\nversion: 1.0.0\ndomain: t\ndescription: a thing\nruntime: prompt\n---\n"
        "# Bare\n\n## When to use\nx\n",
        encoding="utf-8",
    )
    reg = build_registry()
    with pytest.raises(SpecError) as exc:
        reg.load_domain(tmp_path / "skills")
    assert any(e.type == "missing_instructions" for e in exc.value.details)


def test_unknown_placeholder_rejected(tmp_path):
    d = tmp_path / "skills" / "bad"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: bad\nversion: 1.0.0\ndomain: t\ndescription: a thing\nruntime: prompt\n"
        "inputs: {doc: {type: text}}\n---\n# Bad\n\n## Instructions\nSummarise {inputs.wrong}.\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError) as exc:
        build_registry([str(tmp_path / "skills")])
    assert any(e.type == "unknown_placeholder" for e in exc.value.details)


def test_prompt_output_type_rejected(tmp_path):
    d = tmp_path / "skills" / "bad"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: bad\nversion: 1.0.0\ndomain: t\ndescription: a thing\nruntime: prompt\n"
        "outputs: {frame: {type: dataframe}}\n---\n# Bad\n\n## Instructions\nDo it.\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError) as exc:
        build_registry([str(tmp_path / "skills")])
    assert any(e.type == "prompt_output_type" for e in exc.value.details)


def test_prompt_components_in_catalog_and_domains():
    reg = notes_registry()
    assert set(reg.names(["notes"])) == {"summarize_notes", "extract_actions", "note_digest"}
    cat = {c["name"]: c for c in reg.catalog(["notes"])}
    assert cat["summarize_notes"]["params"]["tone"]["required"] is False
    assert cat["extract_actions"]["outputs"]["actions"] == "json"


# ------------------------------------------------------------------ execution
def test_no_llm_is_dependency_error():
    reg = notes_registry()
    plan = parse_plan({"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}, reg)
    rep = PipelineExecutor(reg).run(plan, {"transcript": TRANSCRIPT})
    err = rep.by_id("s").error
    assert rep.by_id("s").status == StepStatus.FAILED
    assert err.category.value == "dependency"


def test_text_output_emitted():
    rep = run_steps(
        notes_registry(),
        {"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]},
        ScriptedBackend(['{"summary": "Ship Friday agreed."}']),
    )
    o = rep.by_id("s")
    assert o.status == StepStatus.OK
    assert rep.artifacts.get("s.summary") == "Ship Friday agreed."
    assert o.result["outputs"]["summary"] == "Ship Friday agreed."


def test_json_output_emitted():
    body = '{"actions": [{"owner": "Ana", "task": "notes", "due": "Friday"}], "decisions": ["ship Friday"]}'
    rep = run_steps(
        notes_registry(),
        {"objective": "digest", "steps": [{"id": "a", "component": "extract_actions"}]},
        ScriptedBackend([body]),
    )
    o = rep.by_id("a")
    assert o.status == StepStatus.OK
    assert rep.artifacts.get("a.actions")[0]["owner"] == "Ana"


def test_wrong_output_type_self_corrects():
    be = ScriptedBackend(['{"actions": "nope"}', '{"actions": [], "decisions": []}'])
    rep = run_steps(
        notes_registry(), {"objective": "digest", "steps": [{"id": "a", "component": "extract_actions"}]}, be
    )
    assert rep.by_id("a").status == StepStatus.OK
    assert len(be.calls) == 2  # rejected once, repaired by feedback


def test_correction_exhausted_is_typed_error():
    be = ScriptedBackend(['{"actions": "nope"}'] * 5)
    rep = run_steps(
        notes_registry(), {"objective": "digest", "steps": [{"id": "a", "component": "extract_actions"}]}, be
    )
    o = rep.by_id("a")
    assert o.status == StepStatus.FAILED
    assert o.error.category.value == "llm_output"


def test_grounding_rejects_invented_numbers():
    be = ScriptedBackend(
        ['{"summary": "Yield rose by 42 percent in 2019."}', '{"summary": "The team agreed to ship Friday."}']
    )
    rep = run_steps(
        notes_registry(), {"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}, be
    )
    assert rep.by_id("s").status == StepStatus.OK
    assert len(be.calls) == 2


def test_template_interpolation():
    be = ScriptedBackend(['{"summary": "ok"}'])
    run_steps(
        notes_registry(),
        {
            "objective": "the goal",
            "steps": [{"id": "s", "component": "summarize_notes", "params": {"tone": "executive"}}],
        },
        be,
    )
    user = be.calls[0]["messages"][1]["content"]
    assert "executive summary" in user and "Objective: the goal" in user and TRANSCRIPT in user


def test_pipeline_over_prompt_steps():
    reg = notes_registry()
    be = ScriptedBackend(['{"summary": "Short."}', '{"actions": [], "decisions": []}'])
    plan = parse_plan(reg.pipeline("note_digest").instantiate({}), reg)
    rep = PipelineExecutor(reg, llm=be, llm_settings=LLMSettings()).run(plan, {"transcript": TRANSCRIPT})
    assert rep.ok
    assert sorted(rep.output_values()) == ["actions", "summary"]


# ------------------------------------------------------------------ agents / config
def test_skill_dirs_in_config():
    cfg = AgentsConfig.load(NOTES)
    assert cfg.skill_dirs and cfg.skill_dirs[0].endswith("skills")


def test_missing_skill_dir(tmp_path):
    (tmp_path / "fabric.md").write_text("---\nroot: a\nskill_dirs: [./nope]\n---\n", encoding="utf-8")
    d = tmp_path / "agents" / "a"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text("---\nname: a\nkind: llm\ndescription: x\n---\nBe brief.\n", encoding="utf-8")
    with pytest.raises(FabricError) as exc:
        AgentsConfig.load(tmp_path)
    assert any(e.type == "missing_skill_dir" for e in exc.value.details)


def test_agent_run_charges_prompt_llm_calls():
    plan = '{"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}'
    be = ScriptedBackend([plan, '{"summary": "Friday ship agreed."}'])
    fabric = AgentFabric(build_registry(), AgentsConfig.load(NOTES), backend=be)
    events, steps = [], []
    rep = fabric.run("Digest this meeting", {"transcript": TRANSCRIPT}, on_event=events.append, on_step=steps.append)
    assert rep.result.status == "ok"
    assert rep.usage["llm_calls"] == 2  # planner call + prompt step
    assert steps[0].step_id == "s"
    assert [e.event for e in events] == ["start", "llm_call", "llm_call", "end"]
