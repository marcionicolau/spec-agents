---
name: medallion_plan
version: 1.0.0
domain: lakehouse
category: design
description: Design bronze, silver and gold Trino/Iceberg tables and the SQL that loads them from an inferred schema.
runtime: code
params:
  catalog: {description: Trino catalog backed by the Iceberg connector, example: lake}
  table: {description: base table name shared by the three layers, example: orders}
  business_keys: {description: source columns that identify a record; required for merge, example: [order_id]}
  load_mode: {description: "merge (upsert on business keys), append or overwrite", example: merge}
  bronze_schema: {description: schema of the raw layer, example: bronze}
  silver_schema: {description: schema of the cleaned layer, example: silver}
  gold_schema: {description: schema of the aggregated layer, example: gold}
  partition_column: {description: date or timestamp column used to partition silver by day; null = unpartitioned, example: order_date}
  gold_group_by: {description: columns to group the gold summary by; empty = one global row, example: [region]}
  gold_measures: {description: numeric columns aggregated as avg/min/max in gold, example: [amount]}
inputs:
  schema: {type: json, description: "column list from source_inspect"}
outputs:
  layout: {type: json, description: "tables, columns and every SQL statement used by the DAG"}
---
# Medallion design

## When to use
After `source_inspect`, to fix where the data lands and how it is promoted between layers.

## When not to use
The target is not Trino on the Iceberg connector: `merge` and `CREATE OR REPLACE TABLE` need Iceberg.

## Interpreting
- Bronze keeps every source column as text plus `_batch_id`, `_source` and `_ingested_at`, so raw data is never lost.
- Silver casts columns to the inferred types with `TRY_CAST` (bad values become null), keeps the latest record per business key and upserts, appends or overwrites according to `load_mode`.
- Gold is rebuilt from silver on every run: row_count plus avg, min and max of each measure per `gold_group_by`.
- Without `business_keys` silver cannot be de-duplicated: re-runs append duplicates and the result carries a warning.

## Common mistakes
- Using source column names instead of the sanitised `name` from the schema.
- Choosing `merge` without `business_keys`.
- Naming a text column in `gold_measures`, or a column in both `gold_group_by` and `gold_measures`.
- Partitioning on a column that is not a date or timestamp.
