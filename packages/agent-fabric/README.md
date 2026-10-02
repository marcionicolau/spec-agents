# spec-agents-core (`agent_fabric`)

Domain-agnostic core for **spec-driven pipelines and hierarchical agents**. Components, pipelines and agents are declared in Markdown
with YAML frontmatter (`SKILL.md`, `AGENT.md`, `fabric.md`); the frontmatter is a contract validated by Pydantic and the body is guidance
injected into prompts on demand. LLMs plan, delegate, repair and interpret — **they never compute**: every result comes from
deterministic `Component.compute()` code run by the `PipelineExecutor`.

> **Status:** pre-release. Until the first PyPI release, install a wheel from the
> [GitHub Releases](https://github.com/marcionicolau/spec-agents/releases) or use `uv sync --all-packages` in a checkout;
> the `pip install` lines below are the PyPI names.

## Install
```bash
pip install spec-agents-core                  # core: pydantic, numpy, pyyaml, rich (import name: agent_fabric)
pip install "spec-agents-core[tabular]"       # + pandas (dataframe artifact types)
pip install "spec-agents-core[all]"           # + PydanticAI, DSPy, CrewAI, LangChain adapters
```
Domain packs ([statistics](../statistics/README.md), [lakehouse](../lakehouse/README.md), [coworker](../coworker/README.md),
[text-pack](../text-pack/README.md)) register themselves through the `agent_fabric.domains` entry point.

## Use
```bash
agent-fabric catalog --skills path/to/skills     # list components and pipelines
agent-fabric agents path/to/config               # render and validate an agent tree
agent-fabric lint --agents path/to/config --strict
agent-fabric run path/to/config "task" --input name=file.txt
```
```python
from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig

fabric = AgentFabric(build_registry(discover=True), AgentsConfig.load("config"))
report = fabric.run("question", {"data": df}, session_id="s1")
```

Optional frameworks are imported lazily; models are referenced by LiteLLM alias only. See the repository
[docs](../../docs/README.md) for the architecture, the error model and how to add components, pipelines and agents.
