# spec-agents-text (`text_pack`)

Small text domain pack for [agent-fabric](../agent-fabric/README.md): components `text_stats` and `keywords`, pipeline `document_digest`.
It needs no pandas and no other pack, which makes it the proof that the core is domain-agnostic, and a minimal template for new packs.

> **Status:** pre-release. Until the first PyPI release, install a wheel from the
> [GitHub Releases](https://github.com/marcionicolau/spec-agents/releases) or use `uv sync --all-packages` in a checkout;
> the `pip install` lines below are the PyPI names.

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
