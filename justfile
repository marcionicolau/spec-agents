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
    just skills-export

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

# export every skill as a spec-compliant Agent Skill (agentskills.io) into build/skills and validate it with the
# official skills-ref validator (agentskills CLI, pinned in the dev group); our own validator also runs inside export-skills
skills-export:
    rm -rf build/skills
    uv run agent-fabric export-skills --out build/skills --domains stat_fabric.domain:register text_pack:register lake_fabric.domain:register coworker_fabric.domain:register --skills examples/notes/skills
    rc=0; for d in build/skills/*/; do uv run agentskills validate "$d" || rc=1; done; [ $rc -eq 0 ]

# The documentation is one GitHub Pages site made of two builds (Node 22+ and pnpm for Docusaurus, see .node-version and website/package.json):
#   /           Docusaurus (website/): usage guides and examples taken from examples/docs
#   /reference/ MkDocs Material (docs/): contributor guides + generated API reference
# `just docs-all` builds both into build/site; warnings and broken links fail either build.

# Docusaurus guide site into build/site (clears it first, so run docs-api afterwards or use docs-all)
docs-doc:
    #!/usr/bin/env bash
    set -euo pipefail
    major=$(node -p 'process.versions.node.split(".")[0]')
    [ "$major" -ge 22 ] || { echo "Node 22+ is required (found $(node -v)); see .node-version" >&2; exit 1; }
    cd website
    pnpm install --frozen-lockfile
    pnpm run build --out-dir ../build/site

# MkDocs site (contributor guides + generated API reference) into build/site/reference; strict
docs-api:
    DISABLE_MKDOCS_2_WARNING=true uv run mkdocs build

# the whole site, as published: Docusaurus at /, MkDocs at /reference/
docs-all: docs-doc docs-api

# alias kept for older habits and workflows
docs: docs-all

# live-reloading previews; `just docs-serve` builds, watches and serves BOTH — MkDocs at http://127.0.0.1:8000 and
# Docusaurus at http://localhost:3000/spec-agents/ — until Ctrl-C; `just docs-serve doc|api` serves only one side
docs-serve which="both":
    #!/usr/bin/env bash
    set -euo pipefail
    serve_doc() { cd website && pnpm install --frozen-lockfile && exec pnpm start; }
    serve_api() { DISABLE_MKDOCS_2_WARNING=true exec uv run mkdocs serve; }
    case "{{which}}" in
        doc) serve_doc ;;
        api) serve_api ;;
        both)
            serve_doc & doc_pid=$!
            serve_api & api_pid=$!
            trap 'kill "$doc_pid" "$api_pid" 2>/dev/null || true' EXIT
            wait -n "$doc_pid" "$api_pid"
            ;;
        *) echo "usage: just docs-serve [both|doc|api]" >&2; exit 2 ;;
    esac

# rebuild conflicting release-please PR branches on main (they all edit the shared manifest); `just release-sync --dry-run` only reports.
# Needs `gh` authenticated (GH_TOKEN, e.g. `GH_TOKEN=$(gh auth token) just release-sync`); CI does this automatically after each release.
release-sync *args:
    python3 tools/release_sync.py --repo marcionicolau/spec-agents {{args}}

# SKILL.md contract changes vs. the base branch must carry a version bump (CI runs this on PRs)
contracts base="origin/main":
    uv run python -m agent_fabric.contracts --base {{base}}

# type check (ty) with every optional framework installed so their imports resolve
types:
    uv run --all-extras ty check

# regression gate for the deterministic eval suites (CI); `just evals-update` rewrites the baseline file (review the diff)
evals-check:
    uv run python examples/check_baselines.py

evals-update:
    uv run python examples/check_baselines.py --update

# deterministic planner baseline; `just evals live` needs the LiteLLM proxy
evals mode="rules":
    uv run python examples/run_evals.py --mode {{mode}}

# start the LiteLLM gateway at http://localhost:<port>/v1 in front of Ollama ($OLLAMA_API_BASE); override: `just litellm 4001 other.yaml`
litellm port="4000" config="config/litellm_config.yaml":
    OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://localhost:11434}" LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-local-dev}" uv run --all-extras litellm --config {{config}} --port {{port}}

# local guard against direct pushes to main (this repo has no server-side branch protection)
hooks:
    git config core.hooksPath tools/hooks
    @echo "hooks installed: direct pushes to main are blocked locally"

# everything CI runs
check: lint specs test build
