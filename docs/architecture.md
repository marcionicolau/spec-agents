# Architecture

## Stack

| Concern                   | Library             | Where                               | Role                                                                 |
| ------------------------- | ------------------- | ----------------------------------- | -------------------------------------------------------------------- |
| Contracts                 | Pydantic v2         | everywhere                          | specs, params, results, plans, agent configs, errors                 |
| Structured runs           | PydanticAI          | `llm/planner.py`, `agents/kinds.py` | planner with `ModelRetry`; supervisor delegating via tool calls      |
| Prompt optimisation       | DSPy                | `integrations/dspy.py`              | planner signature; validators = metric; `BootstrapFewShot`           |
| Multi-agent orchestration | CrewAI              | `integrations/crewai.py`            | tree → hierarchical crew; each worker's tool runs the _fabric_ agent |
| Memory                    | LangChain           | `memory/langchain_adapter.py`       | `MemoryPort` adapter over any `BaseChatMessageHistory`               |
| Gateway                   | LiteLLM proxy :4000 | `config/litellm_config.yaml`        | aliases, fallbacks, retries, JSON mode → Ollama                      |

---

## Runtime architecture

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
