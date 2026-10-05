# CLAUDE.md — agent-fabric

Guidance for Claude Code and other coding agents working in this repository.
Read §1 first. The exact procedures live in [docs/](docs/README.md): **read the matching document before you
add a component, pipeline or agent, or before you change guidance text**.

| You are about to…                                                                  | Read first                                   |
| ---------------------------------------------------------------------------------- | -------------------------------------------- |
| add a component, a `runtime: prompt` skill, a pipeline                             | [docs/extending.md](docs/extending.md)       |
| add or change an agent / sub-agent tree                                            | [docs/agents.md](docs/agents.md)             |
| touch errors, `loc`/`type`/`hint`                                                  | [docs/error-model.md](docs/error-model.md)   |
| change a contract, SKILL.md/AGENT.md prose, evals, or the lakehouse/coworker packs | [docs/maintenance.md](docs/maintenance.md)   |
| understand the layers, the run flow, the layout                                    | [docs/architecture.md](docs/architecture.md) |
| cut a release, label an issue, bump a version                                      | [docs/releasing.md](docs/releasing.md)       |

---

## 1. Golden rules (non-negotiable)

1. **LLMs plan, delegate, repair and interpret — they never compute.** Every result comes from
   `PipelineExecutor` → `Component.compute()`. Never add a path where model text becomes data.
   Exception by design: `runtime: prompt` components turn validated/grounded model output into declared
   `text`/`json`/`number`/`any` artifacts — never typed objects like dataframes, see [docs/extending.md](docs/extending.md).
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

---

## 2. Layout (short; details in [docs/architecture.md](docs/architecture.md))

```
packages/agent-fabric/   GENERIC CORE (agent_fabric): specs, registry, pipelines, executor, llm/, agents/, memory/, cli/
packages/statistics/     domain pack (stat_fabric)      packages/lakehouse/  (lake_fabric)
packages/coworker/       domain pack (coworker_fabric)  packages/text-pack/  (text_pack)
packages/<pkg>/tests/    pack tests;  packages/<pkg>/config/  pack demo agent trees (lakehouse, coworker)
tests/                   cross-package suite (core + statistics + text packs)
examples/                research_team, notes (code-free domain), docs (scripts embedded in the guide site, run by tests), evals, run_demo.py, run_evals.py
website/                 Docusaurus user guide (Node 24); docs/ is the MkDocs contributor guide + API reference
config/litellm_config.yaml   gateway;   tools/check_wheels.py;   justfile (task runner);   docs/
```

---

## 3. Commands

```bash
just check                                  # everything CI runs (lint, specs, tests, wheels); `just` lists recipes
just types                                  # ty type check on all five packages (needs --all-extras to resolve optional imports)
uv sync --all-packages --group dev          # workspace env (all members editable); add --all-extras for pydantic-ai/dspy/crewai/langchain
uv run pytest -q                            # offline suite (or activate .venv and run pytest)
uv run ruff check . && uv run ruff format .   # see [tool.ruff.lint] for the rule set
# CI (.github/workflows/ci.yml) runs: pytest, ruff (rules F UP E I B SIM RUF PT), the lint commands below, and the eval baseline gate (just evals-check)
python -m agent_fabric.lint --domains stat_fabric.domain:register text_pack:register \
       --agents examples/research_team --schemas stat_fabric.schemas:SCHEMAS --strict
python -m agent_fabric.lint --domains lake_fabric.domain:register --agents packages/lakehouse/config \
       --schemas lake_fabric.schemas:SCHEMAS --strict
python -m agent_fabric.lint --domains coworker_fabric.domain:register --agents packages/coworker/config \
       --schemas coworker_fabric.schemas:SCHEMAS --strict
python -m lake_fabric.generate params.json --sample records.json --out dags   # DAG file, no LLM involved
python -m agent_fabric.scaffold skill my_step --dir packages/statistics/src/stat_fabric/skills --domain statistics
python -m agent_fabric.scaffold prompt my_step --dir examples/notes/skills --domain notes   # code-free skill
python -m agent_fabric.scaffold pack my-pack   # new domain pack under packages/ + repo wiring (release-please, labels, isort)
python examples/run_evals.py --mode live    # before merging guidance/model changes (PRs get `stage:needs-eval`)
just evals-check                            # deterministic eval baselines (CI); `just evals-update` refreshes examples/evals/baselines.json
just docs-all                              # build the whole site: Docusaurus guide (website/, Node 24) at /, MkDocs reference (docs/) at /reference/; `docs-api`/`docs-doc` build one; `just docs-serve` previews
just release-sync                           # rebuild conflicting release-please PR branches on main (CI does it after each push to main)
just skills-export                          # spec-compliant Agent Skills view of every skill into build/skills + official skills-ref validation (CI)

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

---

## 4. Conventions

- Dependencies are managed with `uv` in a workspace: add with `uv add --package <dist> <dep>` (dist names =
  `spec-agents-core`/`spec-agents-statistics`/`spec-agents-lakehouse`/`spec-agents-coworker`/`spec-agents-text`; directories, tags and PR scopes use
  `agent-fabric`/`statistics`/`lakehouse`/`coworker`/`text-pack`), never `pip install` (it desyncs `uv.lock`).
- **Commits are conventional with package scopes**: `feat(statistics): …`, `fix(agent-fabric): …`. PR titles are linted
  (`pr-title` workflow) and, squash-merged, become the commit that **release-please** reads: it keeps one release PR per
  package (`release-please-config.json`, `.release-please-manifest.json`, `release-type: simple`); merging it writes
  `packages/<pkg>/CHANGELOG.md` + `version.txt` and creates the `<pkg>-vX.Y.Z` tag and GitHub Release. A path outside
  `packages/<pkg>/` triggers no bump; cross-cutting changes use `chore`/`ci`/`docs`. Pre-1.0 packages bump minor on breaking changes.
- **Versions are dynamic**: no `version` in any `pyproject.toml`. `uv-dynamic-versioning` (hatchling backend) derives it from
  the latest `<pkg>-v*` git tag (other packages' tags are ignored); a commit after the tag is `X.Y.(Z+1).devN+<sha>`, so
  `uv.lock` never pins a workspace version. Consequences: checkouts need full history and tags (`fetch-depth: 0` in CI), and
  never create or move `<pkg>-v*` tags by hand — release-please owns them (baseline: all packages at `0.0.1`).
- **SKILL.md `version:` fields stay manual** — they mark
  contract changes (minor = new optional field, major = breaking), not releases. `agent_fabric.contracts` (CI on PRs,
  `just contracts`) fails a PR whose contract diff (params, ports, outputs, defaults) lacks the matching bump.
- **Core API level**: packs declare the core API they were written for with `@requires_api(n)` on `register`; the loaders reject a pack
  that needs a newer `agent_fabric.API_LEVEL` (see `docs/maintenance.md#core-api-level`). Bump it only for breaking changes to the pack-facing API.
- Packs depend on the core with a bounded range (`spec-agents-core>=0.0.1,<1`); widen it deliberately when the core makes a
  breaking change. License: MIT (root `LICENSE`, copied into each package).
- Python ≥ 3.12, `from __future__ import annotations`, type hints, ruff line length 120. Generics use PEP 695 syntax
  (`class Component[P: ComponentParams, R: ComponentResult]`, `def f[T](...)`, `type X = ...`), not `TypeVar`/`Generic`.
  Exception: CrewAI inspects some signatures; keep tool `args_schema` models importable at module level.
- `extra="forbid"` on every model an LLM (or YAML author) can produce.
- Prompt _templates_ live in `llm/prompts.py`; domain wording lives in SKILL.md/AGENT.md bodies, never in code.
- Types: every package ships `py.typed`; `ty` (pinned, pre-1.0) checks every `packages/*/src` in CI (`extras` job). Suppress with
  `# ty: ignore[rule]` plus a reason, never a bare `# type: ignore`. `tests/test_boundaries.py` enforces rules 3 and 7
  (no domain-pack imports in the core; optional frameworks only lazily or behind `try/except ImportError`).
- **Public API = `__all__`.** Every package and every public module lists what it exports in `__all__`; everything else is internal
  and may change in any release. Add new public names to `__all__` **with a docstring** (`tests/test_public_api.py` fails
  otherwise; existing debt lives in `tests/public_api_undocumented.txt` and may only shrink, `python tests/test_public_api.py --update`).
  `agent_fabric.__version__` is read from the installed distribution (dynamic version), never hard-coded. Docstrings follow the
  Google convention — ruff `D` rules enforce the style (summary line, blank line before the body); the `D10x` existence rules are
  off because the ratchet already requires docstrings on public names and internal names need none.
- Use `compact()` before sending results to a model.
- Library warnings are captured per step into `result.warnings` as `[library] …`.
- Don't: parse model prose beyond `extract_json`/`extract_text`; catch bare `Exception` outside the
  execute wrapper, builders and adapters; hardcode model names/URLs; add global mutable state other than
  the `@component` declaration list and the builder registry.
