# Domain packs

Domain knowledge lives in packs; the core never imports one. Each pack registers through the `agent_fabric.domains` entry point
(`build_registry(discover=True)` loads every installed pack) or explicitly (`build_registry([stat_fabric.register])`).

| Pack | Import | Components | Pipelines | Demo agents |
| --- | --- | --- | --- | --- |
| `statistics` | `stat_fabric` | `summary`, `linear_model`, `anova`, `time_series`, `pca`, `clustering` | `exploratory_analysis`, `experiment_analysis`, `full_study` | `examples/research_team` |
| `lakehouse` | `lake_fabric` | `source_inspect`, `medallion_plan`, `airflow_dag_render`, `dag_check` | `ingest_to_lakehouse`, `medallion_design` | `packages/lakehouse/config` |
| `coworker` | `coworker_fabric` | `repo_index`, `context_select`, `context_pack`, `code_review`, `patch_propose` | `improve_code`, `propose_patch` | `packages/coworker/config` |
| `text-pack` | `text_pack` | `text_stats`, `keywords`, `summarize_text` | `document_digest`, `document_summary` | `examples/research_team` |

- **statistics**: formulas are built from validated column names; no model-written code runs. Also provides the `stats_rules` planner (no LLM).
- **lakehouse**: generates Airflow DAGs that load CSV/JSON/XLSX/API/MCP sources into Trino/Iceberg bronze, silver and gold tables. Generated code is never
  trusted twice: static template, validated and quoted identifiers, credentials only in Airflow connections, `dag_check` before use.
- **coworker**: picks code context within a token budget (measured by labelled evals), reviews it and validates patch proposals. It never writes to disk and
  only reads allowlisted roots (`COWORKER_ALLOWED_ROOTS`).
- **text-pack**: small and dependency-free; the proof that the core is domain-agnostic and a template for new packs.
- **notes** (`examples/notes`): not a package, a 100% Markdown domain made of `runtime: prompt` skills.

Per-package API: [agent-fabric](reference/agent-fabric.md) · [statistics](reference/statistics.md) · [lakehouse](reference/lakehouse.md) ·
[coworker](reference/coworker.md) · [text-pack](reference/text-pack.md). To write your own pack see [Extending](extending.md).
