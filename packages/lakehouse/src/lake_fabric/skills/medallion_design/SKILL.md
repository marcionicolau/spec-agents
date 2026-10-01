---
name: medallion_design
kind: pipeline
version: 2.0.0
domain: lakehouse
description: Infer the source schema and design the bronze, silver and gold layers without generating code.
params:
  source: {description: "source description (type, path, url, records_path ...)", required: true, example: {type: csv, path: /data/landing/orders.csv}}
  catalog: {description: Trino Iceberg catalog, required: true, example: lake}
  table: {description: base table name, required: true, example: orders}
  business_keys: {description: unique record identifier columns, default: null}
  load_mode: {description: "merge, append or overwrite", default: null}
  gold_group_by: {description: gold grouping columns, default: null}
  gold_measures: {description: numeric columns aggregated in gold, default: null}
inputs:
  sample: {type: json, required: false, description: example records; required for api and mcp}
steps:
- id: inspect
  component: source_inspect
  params: {source: $params.source}
- id: layers
  component: medallion_plan
  params: {catalog: $params.catalog, table: $params.table, business_keys: $params.business_keys, load_mode: $params.load_mode, gold_group_by: $params.gold_group_by, gold_measures: $params.gold_measures}
  inputs: {schema: inspect.schema}
outputs: {layout: layers.layout, schema: inspect.schema}
---
# Medallion design only

## When to use
Review the proposed tables, keys and SQL with the data owner before any code is generated.

## Procedure
1. `source_inspect`: infer the typed columns.
2. `medallion_plan`: design the three layers from them.
