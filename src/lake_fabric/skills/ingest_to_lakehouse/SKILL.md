---
name: ingest_to_lakehouse
kind: pipeline
version: 2.1.0
domain: lakehouse
description: Inspect a source, design bronze/silver/gold Trino tables and generate a verified Airflow ingestion DAG.
params:
  source: {description: "source description shared by all steps (type, path, url, records_path, auth_conn_id, tool ...)", required: true, example: {type: csv, path: /data/landing/orders.csv}}
  dag_id: {description: snake_case DAG id, required: true, example: ingest_orders}
  catalog: {description: Trino Iceberg catalog, required: true, example: lake}
  table: {description: base table name, required: true, example: orders}
  business_keys: {description: unique record identifier columns, default: null}
  load_mode: {description: "merge, append or overwrite", default: null}
  partition_column: {description: date column to partition silver, default: null}
  gold_group_by: {description: gold grouping columns, default: null}
  gold_measures: {description: numeric columns aggregated in gold, default: null}
  schedule: {description: Airflow schedule, default: null}
  start_date: {description: first logical date, default: null}
  watermark_column: {description: incremental loads - column whose highest silver value bounds the next read, default: null}
  watermark_param: {description: api query parameter that receives the watermark, default: null}
inputs:
  sample: {type: json, required: false, description: example records; required for api and mcp}
steps:
- id: inspect
  component: source_inspect
  params: {source: $params.source}
- id: layers
  component: medallion_plan
  params: {catalog: $params.catalog, table: $params.table, business_keys: $params.business_keys, load_mode: $params.load_mode, partition_column: $params.partition_column, gold_group_by: $params.gold_group_by, gold_measures: $params.gold_measures}
  inputs: {schema: inspect.schema}
- id: render
  component: airflow_dag_render
  params: {dag_id: $params.dag_id, source: $params.source, schedule: $params.schedule, start_date: $params.start_date, watermark_column: $params.watermark_column, watermark_param: $params.watermark_param}
  inputs: {layout: layers.layout}
- id: check
  component: dag_check
  inputs: {code: render.code}
outputs: {dag_code: render.code, layout: layers.layout, schema: inspect.schema}
---
# Source to lakehouse DAG

## When to use
Land a file, JSON, spreadsheet, API or MCP tool into Trino tables organised as bronze, silver and gold, run by Airflow.

## Procedure
1. `source_inspect`: infer the typed columns from the file or from a sample of records.
2. `medallion_plan`: fix table names, keys, load mode and the SQL of each layer.
3. `airflow_dag_render`: produce the DAG file from that design.
4. `dag_check`: reject the file unless it is structurally sound and free of secrets and unsafe calls.

## Interpreting
Deliver `dag_code` only when the check step succeeded. Report the tables from `layout` and any warnings from the design step, especially a missing business key.
