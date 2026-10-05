---
id: index
title: Domain packs
---

The core is domain-agnostic; **packs** add the components, pipelines and artifact types of one domain. Each pack has a runnable
example that works offline.

| Pack | Import | What it does | Guide |
| --- | --- | --- | --- |
| text | `text_pack` | text statistics and keywords; the smallest pack, a template for new ones | [Text](text.mdx) |
| statistics | `stat_fabric` | summary, linear models, ANOVA, time series, PCA, clustering | [Statistics](statistics.mdx) |
| lakehouse | `lake_fabric` | generates validated Airflow DAGs that load sources into Trino/Iceberg bronze, silver and gold | [Lakehouse](lakehouse.mdx) |
| coworker | `coworker_fabric` | selects code context within a token budget, reviews code, validates patches | [Coworker](coworker.mdx) |

There is also **notes**, not a package but a 100% Markdown domain of `runtime: prompt` skills (see the
[Quickstart](../quickstart.mdx)). To write your own pack, read
[Extending](pathname:///spec-agents/reference/extending/) in the contributor guides.

The names of every component and pipeline are in the [API reference](pathname:///spec-agents/reference/reference/).
