# agent-fabric

[![CI](https://github.com/marcionicolau/spec-agents/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/marcionicolau/spec-agents/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-informational)](https://marcionicolau.github.io/spec-agents/)
[![PyPI](https://img.shields.io/pypi/v/spec-agents-core?label=pypi%3A%20spec-agents-core)](https://pypi.org/project/spec-agents-core/)
[![Latest release](https://img.shields.io/github/v/release/marcionicolau/spec-agents?display_name=tag&sort=semver)](https://github.com/marcionicolau/spec-agents/releases)
[![License: MIT](https://img.shields.io/github/license/marcionicolau/spec-agents)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/spec-agents-core?logo=python&logoColor=white)](https://pypi.org/project/spec-agents-core/)
[![Typed](https://img.shields.io/badge/typing-typed-informational)](packages/agent-fabric/src/agent_fabric/py.typed)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![uv](https://img.shields.io/badge/packaging-uv-DE5FE9)](https://docs.astral.sh/uv/)
[![Conventional Commits](https://img.shields.io/badge/commits-conventional-FE5196?logo=conventionalcommits&logoColor=white)](https://www.conventionalcommits.org/)
[![Last commit](https://img.shields.io/github/last-commit/marcionicolau/spec-agents)](https://github.com/marcionicolau/spec-agents/commits/main)

A **domain-agnostic core** for spec-driven pipelines and **hierarchical agent trees with sub-agents**, running on local LLMs
(Ollama behind a **LiteLLM proxy**) and integrating **Pydantic/PydanticAI**, **DSPy**, **CrewAI** and **LangChain**.
Statistics, lakehouse, coworker and text are independent _domain packs_; the core imports none of them, and `packages/text-pack`
shows it works for any domain.

> LLMs plan, delegate, repair and interpret; **whatever computes is always deterministic code**.

**Documentation:** <https://marcionicolau.github.io/spec-agents/> (quickstart, concepts, guides, and an API reference generated from the code).
The same pages live in [`docs/`](docs/README.md).

## Packages

A [uv](https://docs.astral.sh/uv/) monorepo under `packages/`. Each package has its own version, derived from its `<package>-vX.Y.Z` git tag
(release-please + `uv-dynamic-versioning`), and its own README.

| Package (PyPI name) | Import | What it is |
| --- | --- | --- |
| [`spec-agents-core`](packages/agent-fabric) | `agent_fabric` | Core: specs, registry, pipelines, executor, agents, LLM planners, memory, CLI |
| [`spec-agents-statistics`](packages/statistics) | `stat_fabric` | Summary, linear model, ANOVA, time series, PCA and clustering |
| [`spec-agents-lakehouse`](packages/lakehouse) | `lake_fabric` | Generation and verification of Airflow DAGs (Trino/Iceberg, medallion layers) |
| [`spec-agents-coworker`](packages/coworker) | `coworker_fabric` | Pair programming: context selection, static review, patch proposals |
| [`spec-agents-text`](packages/text-pack) | `text_pack` | A minimal text domain; the template for new packs |

Install from PyPI: `pip install spec-agents-core` plus the packs you need (`spec-agents-statistics`, `spec-agents-lakehouse`, `spec-agents-coworker`,
`spec-agents-text`); the import names are in the table. Every [GitHub Release](https://github.com/marcionicolau/spec-agents/releases) also carries the wheel
and sdist of its package, and PyPI files have build provenance attestations. Git tags and PR scopes use the short package names (`agent-fabric-v0.5.0`, `feat(statistics): ...`). A pack declares the core API level it was
written for (`@requires_api(1)`, compared with `agent_fabric.API_LEVEL`) and the loader rejects incompatible packs with a located error.

## Markdown specs: contract + guidance

Everything is a Markdown file with YAML frontmatter:

- **frontmatter = contract**, validated by Pydantic;
- **body = natural-language guidance**, loaded into prompts only when needed.

| File | What it declares | Validated when |
| --- | --- | --- |
| `skills/<name>/SKILL.md` | a **component** (typed ports, params) or a **pipeline** (`kind: pipeline`, a DAG with `$params`) plus the sections _When to use_, _Interpreting_, _Common mistakes_ | at registration (spec ↔ code contract, references, types) |
| `config/agents/<name>/AGENT.md` | an **agent** (kind, sub-agents, model, ...); the body is its _system prompt_ | before a run (the whole tree: references, cycles, depth) |
| `config/fabric.md` | `root`, `budget`, `llm` | on load |

Where the guidance reaches the prompts:

- **planner catalogue:** `description` + the first paragraph of _When to use_;
- **interpreter:** the _Interpreting_ section;
- **parameter repair and feedback on rejected plans:** the _Common mistakes_ section;
- **`references/` folder:** read only on demand;
- **`runtime: prompt`:** the _Instructions_ section is the prompt template, so a `SKILL.md` alone is a component with no Python class (see below).

## Code-free domains (`runtime: prompt`)

A `SKILL.md` with `runtime: prompt` is a complete component: no Python package, no `register()`:

```markdown
---
name: summarize_notes
version: 1.0.0
domain: notes
description: Condense a meeting transcript into a short faithful summary.
runtime: prompt
params:
  tone: {description: "writing tone for the summary", required: false, default: neutral}
inputs:
  transcript: {type: text, constraints: {min_chars: 20}}
outputs:
  summary: {type: text}
---
# Summarize notes

## Instructions
Write a {params.tone} summary of the meeting below, at most 120 words. Cover what was
discussed and what was agreed; do not add anything that is not in the transcript.

Transcript:
{inputs.transcript}
```

- The template accepts `{params.<name>}`, `{inputs.<port>}` and `{objective}`, validated against the contract at registration; literal braces are escaped as `{{ }}`.
- With declared `outputs` the model answers a validated, self-corrected JSON object; without `outputs`, free text is the output. Output ports are only `text`/`json`/`number`/`any`:
  a prompt step never feeds a `dataframe` port, so the deterministic-compute boundary still holds.
- `prompt: {model, temperature, grounding}` in the frontmatter overrides the agent's defaults; `grounding` (on by default) rejects numbers invented in the output.
- `config/fabric.md` accepts `skill_dirs: [./skills]` to load specs relative to the config directory; that is how `examples/notes/` runs entirely in Markdown.
- Scaffold: `python -m agent_fabric.scaffold prompt <name> --dir <pack>/skills --domain <domain>`.

## Agents with sub-agents

```
research_lead (supervisor, router)           fallback: rules
├── stats_team (supervisor, sequential)
│   ├── statistician (planner, domain statistics)   fallback: stats_rules
│   └── methods_reviewer (llm, structured Review output, grounding)
├── profile_runner (pipeline: exploratory_analysis)
└── notes_digest (pipeline: document_summary)          ← text domain
```

- **router:** the LLM produces a validated delegation plan (existing agents, blackboard keys, `@d1` to pass outputs, acyclic dependencies) with self-correction; dependents of failed delegations are skipped.
- **sequential:** passes each child's output to the next; **pydantic_ai:** delegates through _tool calls_.
- A per-run **budget** (depth, runs, delegations, LLM calls), a **trace** with paths (`research_lead/stats_team/statistician`), **per-agent memory**, and **fallbacks** at build and run time.
- **CrewAI:** `build_crew()` maps the tree to a hierarchical crew whose tools run the fabric's agents.

## Other domains

| Domain | Package | Agents | What it does |
| --- | --- | --- | --- |
| `lakehouse` | `packages/lakehouse` | `packages/lakehouse/config` (`lakehouse_team`, `dag_engineer`, `dag_reviewer`, `schema_designer`) | Generates Airflow DAGs that load CSV, JSON, XLSX, API or MCP-tool sources into Trino/Iceberg tables in bronze, silver and gold layers |
| `coworker` | `packages/coworker` | `packages/coworker/config` (`pair_programmer`, `context_scout`, `code_critic`, `patch_author`) | Pair programming: picks the context within a token budget, reviews code and validates patch proposals |
| `notes` | none (Markdown only) | `examples/notes` (`note_taker`) | Code-free demo: summary, action extraction and meeting digest through `runtime: prompt` |

**Lakehouse.** Pipeline `ingest_to_lakehouse`: `source_inspect` → `medallion_plan` → `airflow_dag_render` → `dag_check`. The DAG code comes from a static
template and no value is interpolated into code or SQL; credentials stay in Airflow connections. The `batch_id` derives from the `run_id`, so a retry of the same
run reloads its own batch without duplicating rows. APIs can be paginated (`next_link`, `cursor` or `page`; exhausting `max_pages` fails the run instead of loading
partial data) and loads can be incremental (`watermark_column`, with `merge`). Without an LLM, straight from a parameters JSON:

```bash
python -m lake_fabric.generate params.json --sample records.json --out dags
# params.json: {"source": {"type": "csv", "path": "/data/orders.csv"}, "dag_id": "ingest_orders",
#               "catalog": "lake", "table": "orders", "business_keys": ["order_id"]}
```

**Coworker.** Pipelines `improve_code` (index, context, bundle and static review) and `propose_patch` (edits applied only in memory, restricted to the chosen
context, returned as a unified diff). Nothing is written to disk. Context selection is measured: `python -m coworker_fabric.evals --root .` runs labelled cases
(no LLM) and reports recall, precision and tokens; large files enter only with the relevant symbols.

```bash
python -m agent_fabric.lint --domains lake_fabric.domain:register --agents packages/lakehouse/config \
       --schemas lake_fabric.schemas:SCHEMAS --strict
python -m agent_fabric.lint --domains coworker_fabric.domain:register --agents packages/coworker/config \
       --schemas coworker_fabric.schemas:SCHEMAS --strict
python examples/run_evals.py --domain lakehouse --mode live     # planner regression (proxy up)
python examples/run_evals.py --domain coworker --mode live
```

## Maintenance

- `python -m agent_fabric.lint ... --strict`: detects drift between text and contract (unknown identifiers, missing sections, broken links, texts too long for small
  models, unmentioned sub-agents, weak descriptions) and validates the agent tree.
- `python -m agent_fabric.contracts --base origin/main`: fails when a `SKILL.md` contract changed without the matching `version:` bump (CI runs it on PRs).
- `python examples/run_evals.py --mode live`: planner regression. Run it when you change a skill's text or swap models, because text changes behaviour without changing code.
  The deterministic suites are gated against stored baselines in CI (`just evals-check`).
- `python -m agent_fabric.scaffold skill|pipeline|agent <name> --dir ...`: creates files with the canonical sections.
- `agent-fabric export-skills --out DIR`: writes a spec-compliant [Agent Skills](https://agentskills.io/specification) view of every skill.

## `agent-fabric` CLI

One interface (rich: colours, tables, a live view with a spinner; `--plain` or a non-TTY gives plain text):

```bash
agent-fabric catalog --skills examples/notes/skills            # table: name, kind, domain, params, ports (installed packs are discovered; --no-discover to skip)
agent-fabric agents examples/notes                             # agent tree + validation
agent-fabric lint --agents examples/research_team --domains stat_fabric.domain:register --strict   # coloured issue table
agent-fabric run examples/notes "Summarise the meeting" --input transcript=meeting.txt             # live view on a TTY
```

`--input` accepts `name=path` (`.txt`/`.md` → text, `.json` → object, `.jsonl` → lines, `.csv`/`.parquet`/`.xlsx` → dataframe).
`run` shows every agent with its status and LLM-call count in real time and, with `--plain`, prints the same Markdown report as `render_markdown`.

## Usage

```bash
uv sync --all-packages --group dev                 # uv workspace (packages/*); commit uv.lock
just check                                         # everything CI runs: lint, specs, tests, wheels (`just` lists the recipes)
just docs-serve                                    # documentation with live reload (`just docs-serve doc` for the Docusaurus guide)
pytest -q                                          # offline test suite
python examples/run_demo.py --mode scripted        # simulated small-model mistakes + self-correction
python examples/run_demo.py --mode offline         # proxy down: controlled degradation
litellm --config config/litellm_config.yaml --port 4000 && python examples/run_demo.py --mode live
```

```python
from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.report import render_markdown
from stat_fabric.domain import register as stats
from stat_fabric.schemas import Review

fabric = AgentFabric(build_registry([stats, my_pack.register]), AgentsConfig.load("examples/research_team"))
fabric.register_schema("Review", Review)
report = fabric.run("How do the treatments affect yield?", {"data": df, "notes": text}, session_id="trial-2026")
print(render_markdown(report))
```

## Contributing, security and license

- **Roadmap and planning:** [ROADMAP.md](ROADMAP.md), the [project board](https://github.com/users/marcionicolau/projects/14) and [GOVERNANCE.md](GOVERNANCE.md).
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). PR titles are conventional with a package scope, and `main` only takes squash-merged PRs with `ci-ok` green.
- **Security:** do not open a public issue; use the [private vulnerability report](https://github.com/marcionicolau/spec-agents/security/advisories/new) ([SECURITY.md](SECURITY.md)).
- **License:** [MIT](LICENSE).
- **Coding assistants:** [CLAUDE.md](CLAUDE.md) (rules) and [docs/](docs/README.md) (procedures).
