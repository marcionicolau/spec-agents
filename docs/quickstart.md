# Quickstart

Everything below runs offline (no LLM, no proxy): a scripted backend plays the model. Run the commands from a checkout of the
repository; the packages are not published to an index yet.

## 1. Install the workspace

```bash
git clone https://github.com/marcionicolau/spec-agents && cd spec-agents
uv sync --all-packages --group dev        # add --all-extras for PydanticAI, DSPy, CrewAI, LangChain
uv run agent-fabric catalog --skills examples/notes/skills
```

`catalog` lists every registered component and pipeline: here the three Markdown-only skills of the `notes` demo domain.

## 2. Run a pipeline of deterministic components

Components are declared in `SKILL.md` files and implemented in code; a **pipeline** is a spec that wires them. The text pack ships one,
`document_digest` (text statistics + top keywords). No model is involved: results come from `Component.compute()`.

```python
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
```

`parse_plan` validates the plan (structure, registry, ports, types, static constraints) and reports **all** errors at once as a typed
`PlanValidationError`; the executor then runs the steps in dependency order and skips the dependents of a failed step.

## 3. Run an agent tree

An agent tree is declared in `AGENT.md` files plus a `fabric.md` (root, budget, model aliases). The `notes` demo has one planner agent:
the model *plans* which components to run, the components do the work. A `ScriptedBackend` replays two model answers: the plan, then
the output of the `runtime: prompt` step.

```python
from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.llm import ScriptedBackend
from agent_fabric.report import render_markdown

backend = ScriptedBackend(
    [
        '{"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}',  # the planner's answer
        '{"summary": "Ship on Friday; Ana owns the release notes."}',  # the prompt step's answer
    ]
)
fabric = AgentFabric(build_registry(), AgentsConfig.load("examples/notes"), backend=backend)
report = fabric.run("Digest this meeting", {"transcript": "We agreed to ship on Friday. Ana owns the release notes."})
assert report.result.status == "ok"
print(report.usage)  # {'agent_runs': 1, 'delegations': 0, 'llm_calls': 2}
print(render_markdown(report))  # agent tree, per-agent results and the event trace
```

Every LLM call is charged to the budget in `fabric.md` (`max_llm_calls`, `max_depth`, ...), so a run cannot loop forever.

## 4. Use a real model

Start the LiteLLM gateway (aliases `local-planner`, `local-writer`, `local-fast` map to your Ollama models in
`config/litellm_config.yaml`) and drop the scripted backend:

```bash
export OLLAMA_API_BASE=http://localhost:11434 LITELLM_MASTER_KEY=sk-local-dev
litellm --config config/litellm_config.yaml --port 4000
uv run agent-fabric run examples/notes "Digest this meeting" --input transcript=meeting.txt
```

## 5. Check your specs

```bash
uv run agent-fabric agents examples/notes                    # render and validate the agent tree
uv run agent-fabric lint --agents examples/notes --strict    # text vs contract drift, descriptions, links
uv run agent-fabric export-skills --out build/skills --skills examples/notes/skills   # spec-compliant Agent Skills view
```

## Next

- [Concepts](concepts.md): the mental model in one page.
- [Extending](extending.md): add a component, a code-free `runtime: prompt` skill, a pipeline.
- [Agents](agents.md): kinds, backends, the router, budgets and fallbacks.
- [API reference](reference/index.md) and [CLI reference](reference/cli.md).
