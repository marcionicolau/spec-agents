# Agents and sub-agents

`config/fabric.md` holds `root`, `budget`, `llm` (frontmatter; body = human docs) plus `skill_dirs`
(directories of SKILL.md specs resolved relative to the config dir — this is how code-free domains like
`examples/notes/` are loaded; `python` domain loaders still apply via `--domains`/`build_registry`).
Each agent is `config/agents/<name>/AGENT.md`:

```markdown
---
name: stats_team # == folder name
kind: supervisor
strategy: sequential
sub_agents: [statistician, methods_reviewer]
role: Statistics team
description: One line - what parent routers see when deciding to delegate here.
---

Working instructions (this body is the agent's system prompt, after an optional role/goal header).
Mention sub-agents and components in `backticks` so the lint can verify them.
```

Frontmatter fields (`AgentSpec`): `kind`, `backend`, `fallback`, `role`, `goal`, `backstory`, `description`,
`model`, `temperature`, `max_retries`, `sub_agents`, `strategy`, `synthesize`, `max_delegations`, `domains`,
`pipeline`, `function`, `output_schema`, `interpret`, `inputs`, `options`. `instructions` and `source` are
derived from the file and must not appear in frontmatter. An agent needs a `goal`, a `description` or a body.
Loading reports **all** file problems at once, located by relative path.

| kind         | backends                                                                                    | notes                                                                      |
| ------------ | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `supervisor` | `fabric` (router/sequential), `rules` (sequential, no LLM), `pydantic_ai` (tool delegation) | owns `sub_agents`                                                          |
| `planner`    | `fabric`, `pydantic_ai`, `dspy`, `template`, `stats_rules`                                  | plans over `domains`, executes, interprets                                 |
| `pipeline`   | `fabric`                                                                                    | runs `pipeline` with `options.params`; inputs mapped by name, then by type |
| `llm`        | `fabric`                                                                                    | free text or `output_schema`; `options.check_grounding`                    |
| `function`   | `fabric`                                                                                    | registered callable `(task, inputs) -> dict`                               |

**Validation before run** (`AgentFabric.validate`): unknown kind/backend/sub-agent/pipeline/function/
schema/domain (with suggestions), self-reference, duplicates, sub-agents on leaf kinds, supervisors without
sub-agents, cycles, depth > `budget.max_depth`.

**Router delegation plan** (validated, self-corrected): `{"delegations":[{"id","agent","instruction","inputs","depends_on"}]}`
— agents must be sub-agents, inputs must be blackboard keys or `@<delegation_id>`; dependencies acyclic;
at most `max_delegations`. Dependents of failed delegations are skipped.

**Blackboard keys**: user inputs by name (`data`, `notes`); agent output at `<path>`; artifacts at
`<path>.<name>` (e.g. `research_lead/profile_runner.labels`). Sequential supervisors pass each child
`child.inputs or parent inputs` + main outputs of earlier siblings.

**Budget**: `max_depth`, `max_agent_runs`, `max_delegations`, `max_llm_calls` (all LLM calls go through
`MeteredBackend`; PydanticAI calls are charged from its usage). Once exhausted, supervisors stop delegating.

**Parallel delegations**: `budget.max_parallel` (default `1` = sequential, as before) lets a router run independent
delegations at the same time, in threads. Delegations run in waves (all dependencies done); budget is charged and
`delegate` events are emitted in plan order before a wave starts, results are returned in plan order, and every trace
event carries a `seq` giving the run a total order. Counters, trace and blackboard are lock-protected. Keep your own
function agents and backends thread-safe when you raise it.

**Streaming**: `fabric.run(..., on_delta=fn)` (and the CLI live view) receives `fn(path, text)` for the answer text of every
LLM call as it is generated, when the backend can `stream()` (`LiteLLMProxyBackend`, `ScriptedBackend`); other backends just
don't stream. The returned text, the budget and the trace are identical with or without a listener. Async callers can use
`acomplete`/`astream` on the backends (`AsyncLLMBackend`, `StreamingLLMBackend`; `SyncToAsyncBackend` adapts any sync one).

**Trace export**: the `on_event` stream can be persisted two ways. `agent_fabric.trace.JsonlTraceSink` (or
`write_jsonl(report.trace, path)` after the run) writes every event as one JSON line with stable field names —
`seq` (total order), `at` (seconds since run start), `path` (agent path), `event` (`start`/`end`/`llm_call`/
`delegate`/`fallback`/`skip`/`error`), `detail` — flushed per event so a crashed run keeps its trace:

```json
{
  "seq": 3,
  "at": 0.41,
  "path": "note_taker",
  "event": "llm_call",
  "detail": "local-fast"
}
```

The CLI does it with `agent-fabric run <config> ... --trace-out run.jsonl`. `OtelTraceSink` (CLI flag `--otel`,
needs `pip install 'spec-agents-core[otel]'`) maps a run to OpenTelemetry: an agent run is a span (`start` opens,
`end` closes with an ERROR status on failure), `llm_call` opens a child span closed by the next event at the same
path, and `delegate`/`fallback`/`skip`/`error` become span events on the nearest ancestor span. With no
app-configured tracer provider, a console provider printing finished spans is installed so `--otel` alone shows
output; under `opentelemetry-instrument` or an app provider, spans go to its exporters.

**Fallbacks**: build-time and run-time; recorded in `result.notes` and trace (`fallback` event).
**Memory**: per agent at `<session>/<path>`; routers/planners receive their last runs as context.

Adding a kind/backend: `@AgentFabric.builder(kind, backend, accepts_sub_agents=..., requires=(...))`
returning a `BaseAgent` subclass implementing `_run(task, ctx, path, depth)`. Planner backends:
`planner_builder(name, make)` with `make(fabric, spec, metered_backend) -> Planner`.

---
