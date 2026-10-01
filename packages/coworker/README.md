# coworker

Coworker (pair-programming) domain pack for [agent-fabric](../agent-fabric/README.md): `repo_index`, `context_select`, `context_pack`,
`code_review`, `patch_propose` and the pipelines `improve_code` and `propose_patch`. Context selection is measured (BM25-flavoured scorer,
labeled cases, `python -m coworker_fabric.evals`), and **nothing is ever written to disk**: patches are applied in memory and returned
as a unified diff.

Only the working directory and the directories in `COWORKER_ALLOWED_ROOTS` can be indexed or patched; all paths go through
`analysis.safe_path`.

> **Status:** pre-release, not published to an index yet. From a checkout of the repository use `uv sync --all-packages`;
> the `pip install` lines below describe the intended published names.

## Install
```bash
pip install coworker
python -m coworker_fabric.evals --root .      # deterministic context-selection eval
```
Demo agent team (`pair_programmer`, `context_scout`, `code_critic`, `patch_author`): `config/` in the repository.
