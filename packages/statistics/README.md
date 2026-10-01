# statistics

Statistics domain pack for [agent-fabric](../agent-fabric/README.md): deterministic components `summary`, `linear_model`, `anova`,
`time_series`, `pca`, `clustering` and the pipelines `exploratory_analysis`, `experiment_analysis`, `full_study`. Formulas are built from
validated column names; no model-written code is executed. Also provides `StatsRulePlanner` (planner backend `stats_rules`, no LLM).

> **Status:** pre-release, not published to an index yet. From a checkout of the repository use `uv sync --all-packages`;
> the `pip install` lines below describe the intended published names.

## Install
```bash
pip install statistics            # pulls agent-fabric, pandas, scipy, statsmodels, scikit-learn
```
The pack registers as the `statistics` domain via the `agent_fabric.domains` entry point:
```python
from agent_fabric import build_registry

registry = build_registry(discover=True)  # or build_registry([stat_fabric.domain.register])
```
Each component's contract and guidance is a `SKILL.md` under `stat_fabric/skills/`.
