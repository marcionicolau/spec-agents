# Task runner shared by developers and CI (https://just.systems). `just` lists recipes.
set shell := ["bash", "-euo", "pipefail", "-c"]

# packages with a pack-level test dir (the core is covered by tests/ and packages/agent-fabric/tests)
packages := "agent-fabric statistics lakehouse coworker text-pack"

default:
    @just --list

# workspace env (all members editable); pass `--all-extras` for pydantic-ai/dspy/crewai/langchain
sync *args:
    uv sync --locked --all-packages --group dev {{args}}

fmt:
    uv run ruff check . --fix
    uv run ruff format .

lint:
    uv run ruff check .
    uv run ruff format --check .

# drift lint of every spec tree (same four runs as CI)
specs:
    uv run python -m agent_fabric.lint --strict --domains stat_fabric.domain:register text_pack:register --agents examples/research_team --schemas stat_fabric.schemas:SCHEMAS
    uv run python -m agent_fabric.lint --strict --domains lake_fabric.domain:register --agents packages/lakehouse/config --schemas lake_fabric.schemas:SCHEMAS
    uv run python -m agent_fabric.lint --strict --domains coworker_fabric.domain:register --agents packages/coworker/config --schemas coworker_fabric.schemas:SCHEMAS
    uv run python -m agent_fabric.lint --strict --domains examples/notes/skills --agents examples/notes
    uv run agent-fabric catalog --skills examples/notes/skills
    uv run agent-fabric agents examples/notes

# `just test` = everything; `just test statistics` = one package (+ cross-package tests/ for agent-fabric)
test pkg="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "{{pkg}}" ]; then uv run pytest -q; exit; fi
    if [ "{{pkg}}" = "agent-fabric" ]; then uv run pytest -q tests packages/agent-fabric; else uv run pytest -q packages/{{pkg}}; fi

build:
    rm -rf dist
    uv build --all-packages --out-dir dist
    uv run python tools/check_wheels.py dist

cov:
    uv run pytest -q --cov --cov-report=term

# SKILL.md contract changes vs. the base branch must carry a version bump (CI runs this on PRs)
contracts base="origin/main":
    uv run python -m agent_fabric.contracts --base {{base}}

# type check (ty) with every optional framework installed so their imports resolve
types:
    uv run --all-extras ty check

# deterministic planner baseline; `just evals live` needs the LiteLLM proxy
evals mode="rules":
    uv run python examples/run_evals.py --mode {{mode}}

# local guard against direct pushes to main (this repo has no server-side branch protection)
hooks:
    git config core.hooksPath tools/hooks
    @echo "hooks installed: direct pushes to main are blocked locally"

# everything CI runs
check: lint specs test build
