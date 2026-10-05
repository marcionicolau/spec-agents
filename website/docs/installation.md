---
id: installation
title: Installation
---

The packages are published as five distributions; install the core plus the packs you need.

| Package | Install | Import |
| --- | --- | --- |
| core | `pip install spec-agents-core` | `agent_fabric` |
| statistics | `pip install spec-agents-statistics` | `stat_fabric` |
| lakehouse | `pip install spec-agents-lakehouse` | `lake_fabric` |
| coworker | `pip install spec-agents-coworker` | `coworker_fabric` |
| text | `pip install spec-agents-text` | `text_pack` |

Packs depend on the core, so installing a pack is enough. Python 3.12 or newer is required.

:::note
If a package is not on PyPI yet, install from a checkout: wheels are also attached to every
[GitHub Release](https://github.com/marcionicolau/spec-agents/releases).
:::

## From a checkout (to run the examples)

```bash
git clone https://github.com/marcionicolau/spec-agents && cd spec-agents
uv sync --all-packages --group dev        # add --all-extras for PydanticAI, DSPy, CrewAI, LangChain
uv run agent-fabric catalog --skills examples/notes/skills
```

`catalog` lists every registered component and pipeline: the Markdown-only skills of the `notes` demo plus every pack installed in
the environment. Packs register through the `agent_fabric.domains` entry point, or explicitly with
`build_registry([register])`.
