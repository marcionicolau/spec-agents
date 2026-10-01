# CLAUDE.md — agent-fabric

Guidance for Claude Code and other coding agents working in this repository.
Read §1 first. §5 (new component), §6 (new pipeline), §8 (new agent / sub-agent tree) and
§9 (maintenance workflow) are exact procedures.

---

## 1. Golden rules (non-negotiable)

1. **LLMs plan, delegate, repair and interpret — they never compute.** Every result comes from
   `PipelineExecutor` → `Component.compute()`. Never add a path where model text becomes data.
   Exception by design: `runtime: prompt` components turn validated/grounded model output into declared
   `text`/`json`/`number`/`any` artifacts — never typed objects like dataframes (§5).
2. **Everything is declared in Markdown with YAML frontmatter, then verified against code.**
   - **Frontmatter = contract** (validated by Pydantic): ports, params, steps, sub-agents, budgets.
   - **Body = guidance** in natural language, injected into prompts _on demand_. The body can never
     widen the contract: limits, allowed values and names live only in frontmatter/code.
   - Components & pipelines: `skills/<name>/SKILL.md`; agents: `config/agents/<name>/AGENT.md`;
     run-wide settings: `config/fabric.md`. Legacy `*.yaml` specs load into the same models.
3. **The core (`packages/agent-fabric`) is domain-agnostic.** Domain knowledge lives in _domain packs_
   (`packages/statistics`, `packages/lakehouse`, `packages/coworker`, `packages/text-pack`).
   Never import a domain pack from the core.
4. **Every failure is a typed `FabricError`** with a located `ErrorReport` (`category`, `loc`, `type`,
   `msg`, `hint`, `recoverable`). Validators collect _all_ errors before raising. No bare exceptions,
   no error strings.
5. **No LLM-authored code or formulas are executed.** (Stats: formulas are built from validated column names.)
6. **Models are referenced by LiteLLM alias only** (`local-planner`, `local-writer`, `local-fast`);
   concrete Ollama models live only in `config/litellm_config.yaml`.
7. **Optional frameworks stay optional** — PydanticAI, DSPy, CrewAI, LangChain are imported lazily in
   adapters/builders. The core imports none of them at module level.
8. **Tests run offline**: `ScriptedBackend`, PydanticAI `FunctionModel`, DSPy `DummyLM`. No proxy in tests (`tests/` = cross-package suite for the core against the statistics + text packs; `packages/<pkg>/tests/` = pack and CLI tests).
9. **Agent trees are bounded**: depth, agent runs, delegations and LLM calls are budgeted per run.

---

## 2. Stack

| Concern                   | Library             | Where                               | Role                                                                 |
| ------------------------- | ------------------- | ----------------------------------- | -------------------------------------------------------------------- |
| Contracts                 | Pydantic v2         | everywhere                          | specs, params, results, plans, agent configs, errors                 |
| Structured runs           | PydanticAI          | `llm/planner.py`, `agents/kinds.py` | planner with `ModelRetry`; supervisor delegating via tool calls      |
| Prompt optimisation       | DSPy                | `integrations/dspy.py`              | planner signature; validators = metric; `BootstrapFewShot`           |
| Multi-agent orchestration | CrewAI              | `integrations/crewai.py`            | tree → hierarchical crew; each worker's tool runs the _fabric_ agent |
| Memory                    | LangChain           | `memory/langchain_adapter.py`       | `MemoryPort` adapter over any `BaseChatMessageHistory`               |
| Gateway                   | LiteLLM proxy :4000 | `config/litellm_config.yaml`        | aliases, fallbacks, retries, JSON mode → Ollama                      |

---

## 3. Architecture

```
                        AgentsConfig (YAML tree) ── validate(): refs, cycles, depth, capabilities
                                   │
             AgentFabric.build ────┴──► BaseAgent tree (builders per (kind, backend))
                                   │
   run(instruction, inputs) ──► RunContext: blackboard · budget · trace · memory
                                   │
   supervisor ── router (LLM DelegationPlan, self-corrected) | sequential | pydantic_ai tools
      ├── supervisor … (any depth ≤ budget.max_depth)
      ├── planner  ── Planner(LLM/PydanticAI/DSPy/template/domain rules) ─► PipelinePlan
      ├── pipeline ── PipelineSpec.instantiate(params)                    ─► PipelinePlan
      ├── llm      ── free text or output_schema (grounded)
      └── function ── registered callable
                                   │
   PipelinePlan ─► parse_plan (structure → registry/ports/types → static constraints on input profiles)
                ─► PipelineExecutor (topological, ArtifactStore, skip dependents, optional ParamRepairer;
                                     carries the run's LLM backend + objective into StepContext for
                                     `runtime: prompt` components, and fires on_step per step)
                ─► Component.execute (params → port types/constraints → compute → Result → warnings)
```

Patterns: Microkernel (registry + plugins), Template Method (`Component.execute`, `BaseAgent.run`),
Composite (pipelines as components; supervisors own agents), Builder registry / Strategy (agent kinds &
backends, planners), Ports & Adapters (`LLMBackend`, `MemoryPort`, artifact types), Blackboard (run context),
Facade (`StatisticalAnalysisFabric`), graceful degradation (`fallback` backends, rule interpreters).

### Directory map

```
packages/<domain>/             uv workspace members; dist name = spec `domain:`, import module unchanged
  agent-fabric/src/agent_fabric/   GENERIC CORE
    errors.py                  taxonomy: spec plan params data execution llm_output dependency agent budget
    artifacts.py               ArtifactType + TypeRegistry (any, json, text, number)
    tabular.py                 dataframe/series types, DatasetProfile, TableConstraints (column roles)
    markdown.py                frontmatter/body parser, canonical sections, Guidance (references on demand)
    spec.py                    ComponentSpec, PortSpec, PipelineSpec (+instantiate), SKILL.md/YAML loaders
    component.py               Component base, ArtifactStore, StepContext, Num
    registry.py                Registry: types, components, pipelines, domains, catalog; @component
    pipeline.py                PipelinePlan/Step, refs, auto-binding, validation, PipelineComponent
    executor.py                PipelineExecutor, PipelineReport, ParamRepairer protocol
    llm/                       backends, self_correction, prompts, planner, interpreter, repair
    agents/                    spec (AgentSpec/AgentsConfig), runtime, base, kinds, fabric (builders)
    memory/                    MemoryPort, InMemoryMemory, LangChainMemory
    integrations/              dspy.py, crewai.py
    report.py                  render_markdown(AgentRunReport)
    lint.py                    drift lint + CLI (python -m agent_fabric.lint); collect_issues() shared with cli/
    prompt.py                  PromptComponent: code-free `runtime: prompt` components (self-correction, grounding)
    evals.py                   planner regression evals (score shared with DSPy metric)
    scaffold.py                templates for SKILL.md / AGENT.md (python -m agent_fabric.scaffold)
    cli/                       agent-fabric CLI (rich): run (live view), lint, catalog, agents, scaffold
  statistics/src/stat_fabric/    STATISTICS PACK (dist 'statistics')
    components/                summary, linear_model, anova, time_series, pca, clustering (code)
    skills/<name>/SKILL.md       contracts + guidance for the 6 components and 3 pipelines
                                 (exploratory_analysis, experiment_analysis, full_study); pca/references/
    rules.py                   StatsRulePlanner (planner backend 'stats_rules');  schemas.py (Review)
    domain.py                  register(registry)  (entry point agent_fabric.domains:statistics)
    app.py                     StatisticalAnalysisFabric facade
  lakehouse/src/lake_fabric/     LAKEHOUSE PACK (dist 'lakehouse'): source_inspect, medallion_plan,
                               airflow_dag_render, dag_check (+ python_source type, medallion.py SQL
                               builders, render.py, generate.py CLI); pipelines ingest_to_lakehouse, medallion_design
  coworker/src/coworker_fabric/  COWORKER PACK (dist 'coworker'): repo_index, context_select, context_pack,
                               code_review, patch_propose (analysis.py = pure ast helpers); pipelines improve_code, propose_patch
packages/text-pack/src/text_pack/ TEXT PACK (dist 'text-pack'): text_stats, keywords, document_digest – proves genericity
packages/<pkg>/tests/            pack tests (statistics, lakehouse, coworker; agent-fabric: CLI + prompt domain)
packages/<pkg>/config/           lakehouse: fabric.md + lakehouse_team, dag_engineer, dag_reviewer, schema_designer
                                 coworker:  fabric.md + pair_programmer, context_scout, code_critic, patch_author
tests/                           cross-package suite: core exercised against the statistics + text packs
config/litellm_config.yaml       gateway (aliases, fallbacks)
examples/research_team/          fabric.md + agents/<name>/AGENT.md (statistics + text research team)
examples/notes/                  code-free demo domain: fabric.md (`skill_dirs`), note_taker planner, 3 prompt skills
examples/evals/                  planner_cases.yaml (regression cases); run_evals.py, run_demo.py
tools/check_wheels.py            asserts built wheels ship skills + LICENSE
justfile                         task runner: sync, fmt, lint, specs, test [pkg], build, evals, check
```

---

## 4. Commands

```bash
just check                                  # everything CI runs (lint, specs, tests, wheels); `just` lists recipes
uv sync --all-packages --group dev          # workspace env (all members editable); add --all-extras for pydantic-ai/dspy/crewai/langchain
uv run pytest -q                            # offline suite (or activate .venv and run pytest)
uv run ruff check . && uv run ruff format .   # see [tool.ruff.lint] for the rule set
# CI (.github/workflows/ci.yml) runs: pytest, ruff (rules F UP E I B SIM RUF PT), the lint commands below, and run_evals --mode rules (informational)
python -m agent_fabric.lint --domains stat_fabric.domain:register text_pack:register \
       --agents examples/research_team --schemas stat_fabric.schemas:SCHEMAS --strict
python -m agent_fabric.lint --domains lake_fabric.domain:register --agents packages/lakehouse/config \
       --schemas lake_fabric.schemas:SCHEMAS --strict
python -m agent_fabric.lint --domains coworker_fabric.domain:register --agents packages/coworker/config \
       --schemas coworker_fabric.schemas:SCHEMAS --strict
python -m lake_fabric.generate params.json --sample records.json --out dags   # DAG file, no LLM involved
python -m agent_fabric.scaffold skill my_step --dir packages/statistics/src/stat_fabric/skills --domain statistics
python -m agent_fabric.scaffold prompt my_step --dir examples/notes/skills --domain notes   # code-free skill
python examples/run_evals.py --mode live    # before merging guidance/model changes

uv run agent-fabric catalog --skills examples/notes/skills          # rich table; also accepts --domains ref/dir
uv run agent-fabric agents examples/notes                           # renders + validates the agent tree
uv run agent-fabric lint --agents examples/notes                    # same engine as -m agent_fabric.lint, rich output
uv run agent-fabric run examples/notes "Digest this" --input transcript=meeting.txt --plain   # run; drop --plain for live view

export OLLAMA_API_BASE=http://localhost:11434 LITELLM_MASTER_KEY=sk-local-dev
litellm --config config/litellm_config.yaml --port 4000

python examples/run_demo.py --mode scripted   # simulated model mistakes, self-correction at each level
python examples/run_demo.py --mode offline    # proxy down: fallbacks
python examples/run_demo.py --mode live       # real proxy + Ollama
python examples/run_demo.py --mode crew       # CrewAI hierarchical mapping
```

---

## 5. Adding a component (any domain)

1. **Skill** `<pack>/skills/<name>/SKILL.md`, where `<pack>` = `packages/<domain>/src/<module>`
   (start from `python -m agent_fabric.scaffold skill <name> ...`):

   ```markdown
   ---
   name: my_step # snake_case, unique, == folder name
   version: 1.0.0
   domain: my_domain # catalogue filter for planners
   description: One line, < 200 chars (sent in every planner catalogue)
   runtime: code # 'prompt' = no Python class, see the prompt-runtime section below
   params: # one entry per Params field (contract-checked)
     top_k: { description: "...", example: 5 }
   inputs: # typed ports; constraints validated by the artifact type
     data: { type: dataframe, constraints: { min_rows: 10, roles: [...] } }
   outputs: # extra outputs; 'result' (the JSON Result) is implicit
     scores: { type: dataframe }
   ---

   # My step

   ## When to use -> planner catalogue (first paragraph only)

   ## When not to use -> planner catalogue (first paragraph only)

   ## Interpreting -> step interpreter prompt (≤ 1500 chars)

   ## Common mistakes -> parameter repair + planner feedback when a plan using it is rejected
   ```

   Put long material in `skills/<name>/references/*.md` and link it; it is read only via
   `Guidance.reference(...)` / `registry.guidance(...)`, never injected automatically.
   Use `backticks` only for real identifiers (params, ports, Result fields, component names): the lint checks them.

2. **Class**:
   ```python
   @component("my_step")
   class MyStep(Component[MyParams, MyResult]):        # stats: TableComponent (port 'data')
       Params, Result = MyParams, MyResult             # ComponentParams / ComponentResult subclasses; floats as Num
       def compute(self, inputs, params, ctx): ...     # ctx.emit("scores", df) for declared outputs
       def extra_checks(self, inputs, params): ...     # runtime, return list[ErrorDetail]
       def extra_static(self, bound, params): ...      # plan time; bound = {port: profile|None}
       def summarize(self, result) -> (headline, findings)   # rule-based interpretation
   ```
3. **Register** via the pack's `register(registry)` → `registry.load_domain(SPEC_DIR, classes)`.
4. **Test**: happy path; each check yields the expected `(loc, type)`; plan-level validation; JSON-serialisable result.
5. Do **not** touch planners, prompts, executor or registry — the catalogue is generated from specs.

New artifact type: subclass `ArtifactType` (`accepts`, `profile`, `Constraints`, `static_check`,
`runtime_check`) and `registry.types.register(...)` in the pack's `register`.

Registration fails on: spec/Params mismatch, unknown port type, invalid port constraints, spec without
implementation. Runtime: emitting an undeclared output or the wrong type raises `SpecError`.

### Prompt components — `runtime: prompt` (no Python)

A SKILL.md can be the entire component: `runtime: prompt` skips the class and `register()` call —
`Registry.load_domain` binds it to `PromptComponent`, which builds Params dynamically from the spec.
The prompt template is the `## Instructions` body section; placeholders `{params.<name>}`,
`{inputs.<port>}` and `{objective}` are validated against the declared contract at registration
(`unknown_placeholder`), missing Instructions is `missing_instructions`, literal braces escape as `{{ }}`.
Outputs must be `text`/`json`/`number`/`any` (`prompt_output_type`) — a prompt step can never feed a
`dataframe` port, so the deterministic-compute boundary holds for typed data. With declared outputs the
model must answer a JSON object (validated, self-corrected, grounded by default — set
`prompt: {grounding: false}` to opt out); with no outputs, free text is taken verbatim. Prompt steps run
inside pipelines and through planner agents; the LLM backend and objective arrive via `StepContext`
(`llm`, `llm_settings`, `objective`) and every call is charged to `budget.max_llm_calls`. No-LLM runs fail
the step as `dependency`. Scaffold: `python -m agent_fabric.scaffold prompt <name> --dir ... --domain ...`.
See `examples/notes/` for a domain that is 100% Markdown.

---

## 6. Adding a pipeline (spec only, no code)

`skills/<name>/SKILL.md` with `kind: pipeline`:

```markdown
---
name: my_pipeline
kind: pipeline
version: 1.0.0
domain: my_domain
description: One line.
params:
  {
    features: { description: ..., required: true },
    k: { description: ..., default: null },
  }
inputs: { data: { type: dataframe } }
steps:
  - { id: pca, component: pca, params: { features: $params.features } }
  - {
      id: clusters,
      component: clustering,
      params: { k: $params.k },
      inputs: { matrix: pca.scores },
    }
outputs: { labels: clusters.labels }
---

# My pipeline

## When to use

## Procedure (why these steps, in this order - required by the lint)
```

References: `$inputs.<name>`, `<step>.<port>` (`result` always exists), `$params.<name>` (templates only;
a `$params` value resolving to `null` is dropped so the component default applies). Unbound ports
auto-bind to a same-named pipeline input, or — if required — to the only type-compatible input.
Registered pipelines are components: they can be steps of other pipelines (nesting depth ≤ 8) and
targets of `kind: pipeline` agents. Invalid references are reported at registration with suggestions.

---

## 7. Error model

| Category          | Class                                           | Recoverable    | Typical fix path                    |
| ----------------- | ----------------------------------------------- | -------------- | ----------------------------------- |
| `spec`            | `SpecError`                                     | no             | developer fixes spec/code           |
| `plan`            | `PlanValidationError`                           | yes            | planner self-correction             |
| `params` / `data` | `ParamsValidationError` / `DataValidationError` | yes            | planner, `LLMParamRepairer`         |
| `execution`       | `ComponentExecutionError`                       | per hint table | report                              |
| `llm_output`      | `LLMOutputError`, `CorrectionExhausted`         | yes / no       | retry loop                          |
| `dependency`      | `DependencyError`                               | no             | skip dependents, fallback backend   |
| `agent`           | `AgentConfigError` / `DelegationError`          | no / yes       | fix config / router self-correction |
| `budget`          | `BudgetExceeded`                                | no             | stop delegating; synthesis skipped  |

Rules: set `loc` (path into plan/params/config), stable snake_case `type`, factual `msg`, actionable `hint`
(`suggest()` for names). Don't create cascades: a port with a bad reference counts as bound.
Nested pipeline errors are re-located as `pipeline.<inner_step>.…`.

---

## 8. Agents and sub-agents

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

**Fallbacks**: build-time and run-time; recorded in `result.notes` and trace (`fallback` event).
**Memory**: per agent at `<session>/<path>`; routers/planners receive their last runs as context.

Adding a kind/backend: `@AgentFabric.builder(kind, backend, accepts_sub_agents=..., requires=(...))`
returning a `BaseAgent` subclass implementing `_run(task, ctx, path, depth)`. Planner backends:
`planner_builder(name, make)` with `make(fabric, spec, metered_backend) -> Planner`.

---

## 9. Maintenance workflow (long-term)

| Change                                             | Required checks                                                                                                                                                                                         |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New/changed contract (frontmatter, Params, Result) | `pytest`; bump `version` (minor = new optional field, major = breaking)                                                                                                                                 |
| Body-only edit (SKILL.md/AGENT.md prose)           | `lint --strict`; `run_evals.py --mode live` — prose changes behaviour without changing code                                                                                                             |
| Model alias swap in `litellm_config.yaml`          | `run_evals.py --mode live`; compare `mean_score` with the last run                                                                                                                                      |
| Coworker scorer / `context_select` change          | `python -m coworker_fabric.evals --root .` (deterministic, labeled cases in `examples/evals/context_cases.yaml`; also asserted in `tests/test_coworker.py`); add a case for every retrieval bug you fix |
| New skill / agent                                  | `scaffold` → fill sections → `lint --strict` → tests for its checks                                                                                                                                     |

Lint rules (`agent_fabric/lint.py`): unknown backticked identifiers, missing canonical sections, broken
relative links (error), description > 200 chars, skill body > 6000 / agent body > 4000 chars, router bodies
that never mention a sub-agent, bodies mentioning agents that are not sub-agents, plus full tree validation.
Evals (`agent_fabric/evals.py`): cases name expected/forbidden components; score = 0.7 valid + 0.1 first try

- 0.2 coverage − 0.3 per forbidden component (same score as the DSPy metric). The rules baseline
  intentionally fails `treatment_effect` (it is objective-blind) — that is what an LLM planner should beat.

Single source of truth: never duplicate a contract in YAML _and_ SKILL.md for the same name (the loader
rejects duplicate names). Keep YAML only for legacy packs.

## 10. Lakehouse and coworker packs (rules specific to them)

- **Generated code is never trusted twice.** `airflow_dag_render` interpolates only `pprint`-ed validated values into a
  static template (no value reaches code or SQL text; SQL identifiers pass `IDENT` and are double-quoted; row values are
  bound parameters). `dag_check` then rejects the file (imports allowlist, eval/exec/subprocess, secrets, destructive SQL,
  missing medallion tasks). Tests execute the generated DAG against stubbed Airflow/Trino modules.
- **Sources never load partially by accident**: API pagination (`next_link` on the same host only, `cursor`, `page`) fails the
  run when `max_pages` is exhausted; incremental loads (`watermark_column`) read the max value from silver, keep records `>=` it,
  and require `load_mode: merge`. An empty increment passes the gate; an empty non-incremental source fails it.
- **Credentials live in Airflow connections** (`trino_conn_id`, `auth_conn_id`), never in params, URLs or generated files.
- **Context selection is measured, not guessed.** `Scorer` (analysis.py) is BM25-flavoured: IDF over the indexed files, path matches x3,
  symbol-name matches x2, tests down-weighted unless asked for, `relative_cutoff` drops weak candidates, and files over a quarter of the
  budget contribute only their matching symbols (`ranges`). The index stores stemmed vocabularies (`terms`) per file and symbol.
- **Coworker never writes to disk.** `patch_propose` applies edits in memory, restricts them to the selected context,
  and returns a unified diff. All paths go through `analysis.safe_path` (no absolute paths, `..` or symlink escapes).
- **Coworker roots are allowlisted**: only the working directory, or the directories in `COWORKER_ALLOWED_ROOTS`
  (os.pathsep-separated), can be indexed, packed, reviewed or patched (`root_not_allowed`). Tests set the variable to `tmp_path`.
- Flow-style YAML in SKILL.md (`{description: ..., example: ...}`): quote any description containing `,` or `:`.

## 11. Conventions

- Dependencies are managed with `uv` in a workspace: add with `uv add --package <dist> <dep>` (dist names =
  `agent-fabric`/`statistics`/`lakehouse`/`coworker`), never `pip install` (it desyncs `uv.lock`).
- **Commits are conventional with package scopes**: `feat(statistics): …`, `fix(agent-fabric): …`. PR titles are linted
  (`pr-title` workflow) and, squash-merged, become the commit that **release-please** reads: it keeps one release PR per
  package (`release-please-config.json`, `.release-please-manifest.json`); merging it tags `<pkg>-vX.Y.Z`, writes
  `packages/<pkg>/CHANGELOG.md`, bumps `pyproject.toml` and `uv.lock`. A path outside `packages/<pkg>/` triggers no bump;
  cross-cutting changes use `chore`/`ci`/`docs`. Pre-1.0 packages bump minor on breaking changes.
- Package versions bump automatically per package; **SKILL.md `version:` fields stay manual** — they mark
  contract changes (minor = new optional field, major = breaking), not releases.
- Packs depend on the core with a bounded range (`agent-fabric>=0.2,<1`); widen it deliberately when the core makes a
  breaking change. License: MIT (root `LICENSE`, copied into each package).
- Python ≥ 3.12, `from __future__ import annotations`, type hints, ruff line length 120. Generics use PEP 695 syntax
  (`class Component[P: ComponentParams, R: ComponentResult]`, `def f[T](...)`, `type X = ...`), not `TypeVar`/`Generic`.
  Exception: CrewAI inspects some signatures; keep tool `args_schema` models importable at module level.
- `extra="forbid"` on every model an LLM (or YAML author) can produce.
- Prompt _templates_ live in `llm/prompts.py`; domain wording lives in SKILL.md/AGENT.md bodies, never in code.
- Use `compact()` before sending results to a model.
- Library warnings are captured per step into `result.warnings` as `[library] …`.
- Don't: parse model prose beyond `extract_json`/`extract_text`; catch bare `Exception` outside the
  execute wrapper, builders and adapters; hardcode model names/URLs; add global mutable state other than
  the `@component` declaration list and the builder registry.
