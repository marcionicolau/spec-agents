# spec-agents-coworker (`coworker_fabric`)

Coworker (pair-programming) domain pack for [agent-fabric](../agent-fabric/README.md): `repo_index`, `context_select`, `context_pack`,
`code_review`, `patch_propose` and the pipelines `improve_code` and `propose_patch`. Context selection is measured (BM25-flavoured scorer,
labeled cases, `python -m coworker_fabric.evals`), and **nothing is ever written to disk**: patches are applied in memory and returned
as a unified diff.

Only the working directory and the directories in `COWORKER_ALLOWED_ROOTS` can be indexed or patched; all paths go through
`analysis.safe_path`.

> **Status:** pre-release. Until the first PyPI release, install a wheel from the
> [GitHub Releases](https://github.com/marcionicolau/spec-agents/releases) or use `uv sync --all-packages` in a checkout;
> the `pip install` lines below are the PyPI names.

## Names

| | |
| --- | --- |
| PyPI distribution | `spec-agents-coworker` |
| Import name | `coworker_fabric` |
| Directory in the monorepo | `packages/coworker` |
| Release tag / PR scope | `coworker-vX.Y.Z` / `coworker` |

The distribution is named `spec-agents-coworker` because the shorter names are taken on PyPI; the import name and the entry point do not change.

## Install
```bash
pip install spec-agents-coworker
python -m coworker_fabric.evals --root .      # deterministic context-selection eval
```
Demo agent team (`pair_programmer`, `context_scout`, `code_critic`, `patch_author`): `config/` in the repository.
