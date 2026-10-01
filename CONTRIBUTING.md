# Contributing

Agent-specific rules and the exact procedures (new component, pipeline, agent) are in [CLAUDE.md](CLAUDE.md) (rules) and [docs/](docs/README.md) (procedures).

## Setup
```bash
uv sync --all-packages --group dev      # add --all-extras for pydantic-ai/dspy/crewai/langchain
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```
`just check` runs everything CI runs (`just` lists recipes; see CLAUDE.md section 3 for the raw commands).

## Issues and labels
Every issue gets one of each: `pkg:*` (package or area), `stage:*` (triage → needs-design → ready → in-progress → needs-review → released;
`blocked` and `needs-eval` as needed) and a type (`bug`, `enhancement`, `documentation`, `type:*`). Issue forms apply `stage:triage` and the `pkg:` label
automatically; PRs get `pkg:` labels from the files they touch. Labels are defined in [.github/labels.yml](.github/labels.yml).

## Pull requests
- Branch from `main`; one concern per PR.
- **The PR title is the commit message** (squash merge) and must be conventional with a package scope:
  `feat(statistics): …`, `fix(agent-fabric): …`. Scopes: `agent-fabric`, `statistics`, `lakehouse`, `coworker`; cross-cutting changes use
  `ci`, `deps`, `docs`, or `chore` with no scope. The scope decides which package release-please bumps.
- Contract changes (ports, params, results) bump the SKILL.md `version:`; guidance-only edits need `run_evals.py --mode live`.
- Tests must run offline (`ScriptedBackend`, `FunctionModel`, `DummyLM`); never require the LLM proxy.

## Security
See [SECURITY.md](SECURITY.md).
