# lakehouse

Lakehouse domain pack for [agent-fabric](../agent-fabric/README.md): turns CSV, JSON, XLSX, API or MCP-tool sources into **generated
Airflow DAGs** that load Trino/Iceberg tables in bronze, silver and gold layers. Components: `source_inspect`, `medallion_plan`,
`airflow_dag_render`, `dag_check`; pipelines `ingest_to_lakehouse`, `medallion_design`.

Generated code is never trusted twice: values are `pprint`-ed into a static template, SQL identifiers are validated and quoted, credentials
live in Airflow connections, and `dag_check` rejects unsafe files. Incremental loads and pagination never load partial data silently.

> **Status:** pre-release, not published to an index yet. From a checkout of the repository use `uv sync --all-packages`;
> the `pip install` lines below describe the intended published names.

## Install and use
```bash
pip install lakehouse
python -m lake_fabric.generate params.json --sample records.json --out dags     # no LLM involved
```
Demo agent team (`lakehouse_team`, `dag_engineer`, `dag_reviewer`, `schema_designer`): `config/` in the repository.
