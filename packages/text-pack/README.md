# spec-agents-text (`text_pack`)

Small text domain pack for [agent-fabric](../agent-fabric/README.md): components `text_stats`, `keywords` and `summarize_text` (`runtime: prompt`); pipelines `document_digest` (deterministic) and `document_summary` (adds an LLM-written summary).
It needs no pandas and no other pack, which makes it the proof that the core is domain-agnostic, and a minimal template for new packs.

> **Install:** `pip install spec-agents-text` ([PyPI](https://pypi.org/project/spec-agents-text/)); wheels and sdists are also attached to each
> [GitHub Release](https://github.com/marcionicolau/spec-agents/releases) (`text-pack-vX.Y.Z`).

## Names

| | |
| --- | --- |
| PyPI distribution | `spec-agents-text` |
| Import name | `text_pack` |
| Directory in the monorepo | `packages/text-pack` |
| Release tag / PR scope | `text-pack-vX.Y.Z` / `text-pack` |

The distribution is named `spec-agents-text` because the shorter names are taken on PyPI; the import name and the entry point do not change.

## Install
```bash
pip install spec-agents-text
```
```python
from agent_fabric import build_registry
from text_pack import register

registry = build_registry([register])
```
Start a new pack from this one: a `register(registry)` function, `skills/<name>/SKILL.md` contracts and an `agent_fabric.domains` entry point.
