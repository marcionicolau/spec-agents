# spec-agents-lakehouse (`lake_fabric`)

Lakehouse domain pack for [agent-fabric](../agent-fabric/README.md): turns CSV, JSON, XLSX, API or MCP-tool sources into **generated
Airflow DAGs** that load Trino/Iceberg tables in bronze, silver and gold layers. Components: `source_inspect`, `medallion_plan`,
`airflow_dag_render`, `dag_check`; pipelines `ingest_to_lakehouse`, `medallion_design`.

Generated code is never trusted twice: values are `pprint`-ed into a static template, SQL identifiers are validated and quoted, credentials
live in Airflow connections, and `dag_check` rejects unsafe files. Incremental loads and pagination never load partial data silently.

> **Status:** pre-release. Until the first PyPI release, install a wheel from the
> [GitHub Releases](https://github.com/marcionicolau/spec-agents/releases) or use `uv sync --all-packages` in a checkout;
> the `pip install` lines below are the PyPI names.

## Names

| | |
| --- | --- |
| PyPI distribution | `spec-agents-lakehouse` |
| Import name | `lake_fabric` |
| Directory in the monorepo | `packages/lakehouse` |
| Release tag / PR scope | `lakehouse-vX.Y.Z` / `lakehouse` |

The distribution is named `spec-agents-lakehouse` because the shorter names are taken on PyPI; the import name and the entry point do not change.

## Install and use
```bash
pip install spec-agents-lakehouse
python -m lake_fabric.generate params.json --sample records.json --out dags     # no LLM involved
```
Demo agent team (`lakehouse_team`, `dag_engineer`, `dag_reviewer`, `schema_designer`): `config/` in the repository.
