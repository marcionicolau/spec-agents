# Concepts

**One rule drives the design: LLMs plan, delegate, repair and interpret; they never compute.** Every number, table or file comes from
deterministic code (`Component.compute()`) run by the `PipelineExecutor`. Model text only ever becomes data in declared
`runtime: prompt` steps, and only as `text`, `json`, `number` or `any` artifacts that are validated (and, by default, checked for invented
numbers).

| Concept | What it is | Declared in |
| --- | --- | --- |
| **Component** | A deterministic step with typed input ports, parameters and outputs (`runtime: code`), or a prompt template (`runtime: prompt`) | `skills/<name>/SKILL.md` (+ a Python class for `code`) |
| **Pipeline** | A DAG of components; itself a component, so pipelines nest | `SKILL.md` with `kind: pipeline` |
| **Artifact type** | What flows between steps (`text`, `json`, `number`, `dataframe`, ...) with constraints checked at plan time and run time | `ArtifactType` subclasses registered by a domain |
| **Domain pack** | A package that registers components, pipelines and types (`statistics`, `lakehouse`, `coworker`, `text-pack`) | an `agent_fabric.domains` entry point |
| **Agent** | A node of a tree: `supervisor`, `planner`, `pipeline`, `llm` or `function`; planners produce a plan, supervisors delegate | `config/agents/<name>/AGENT.md` |
| **Run context** | Blackboard, budget, trace and memory shared by one run | created by `AgentFabric.run` |

## Contract and guidance

Each spec has **frontmatter = contract** (validated by Pydantic: ports, params, steps, budgets) and a **body = guidance** in natural
language. The body is injected into prompts on demand (planner catalogue, interpreter, parameter repair) but can never widen the contract.
Long material goes in `references/` and is read only when asked for.

## Failures are typed

Every failure is a `FabricError` carrying located `ErrorReport` entries (`category`, `loc`, `type`, `msg`, `hint`, `recoverable`). Validators
collect all problems before raising, which is what lets a model correct its own plan: the located errors are fed back to it. See the
[error model](error-model.md).

## Bounded by construction

Depth, agent runs, delegations and LLM calls are budgeted per run (`budget` in `fabric.md`); once exhausted, supervisors stop delegating.
Models are referenced by LiteLLM alias only, so swapping a model never touches a spec.

## Where to go next

[Quickstart](quickstart.md) · [Architecture](architecture.md) (layers and the run flow) · [Extending](extending.md) · [Agents](agents.md) ·
[API reference](reference/index.md)
