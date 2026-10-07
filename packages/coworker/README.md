# spec-agents-coworker (`coworker_fabric`)

Coworker (pair-programming) domain pack for [agent-fabric](../agent-fabric/README.md): `repo_index`, `context_select`, `context_pack`,
`code_review`, `draft_edits`, `patch_propose` and the pipelines `improve_code` and `propose_patch`. Context selection is measured (BM25-flavoured scorer,
labeled cases, `python -m coworker_fabric.evals`), and **nothing is ever written to disk**: patches are applied in memory and returned
as a unified diff.

Only the working directory and the directories in `COWORKER_ALLOWED_ROOTS` can be indexed or patched; all paths go through
`analysis.safe_path`.

> **Install:** `pip install spec-agents-coworker` ([PyPI](https://pypi.org/project/spec-agents-coworker/)); wheels and sdists are also attached to each
> [GitHub Release](https://github.com/marcionicolau/spec-agents/releases) (`coworker-vX.Y.Z`).

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
