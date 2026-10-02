# spec-agents-statistics (`stat_fabric`)

Statistics domain pack for [agent-fabric](../agent-fabric/README.md): deterministic components `summary`, `linear_model`, `anova`,
`time_series`, `pca`, `clustering` and the pipelines `exploratory_analysis`, `experiment_analysis`, `full_study`. Formulas are built from
validated column names; no model-written code is executed. Also provides `StatsRulePlanner` (planner backend `stats_rules`, no LLM).

> **Install:** `pip install spec-agents-statistics` ([PyPI](https://pypi.org/project/spec-agents-statistics/)); wheels and sdists are also attached to each
> [GitHub Release](https://github.com/marcionicolau/spec-agents/releases) (`statistics-vX.Y.Z`).

## Names

| | |
| --- | --- |
| PyPI distribution | `spec-agents-statistics` |
| Import name | `stat_fabric` |
| Directory in the monorepo | `packages/statistics` |
| Release tag / PR scope | `statistics-vX.Y.Z` / `statistics` |

The distribution is named `spec-agents-statistics` because the shorter names are taken on PyPI; the import name and the entry point do not change.

## Install
```bash
pip install spec-agents-statistics   # pulls spec-agents-core, pandas, scipy, statsmodels, scikit-learn
```
The pack registers as the `statistics` domain via the `agent_fabric.domains` entry point:
```python
from agent_fabric import build_registry

registry = build_registry(discover=True)  # or build_registry([stat_fabric.domain.register])
```
Each component's contract and guidance is a `SKILL.md` under `stat_fabric/skills/`.
