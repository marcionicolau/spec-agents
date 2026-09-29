---
name: airflow_dag_render
version: 2.1.0
domain: lakehouse
category: generation
description: Render a runnable Airflow DAG file that reads the source and loads bronze, silver and gold in Trino.
params:
  dag_id: {description: snake_case DAG id, example: ingest_orders}
  source:
    description: "source description: type (csv, json, xlsx, api or mcp), plus path/sheet/delimiter/encoding for files, url/method/query/auth_conn_id/timeout for api and mcp, records_path for JSON payloads, tool/arguments for mcp, pagination {mode next_link|cursor|page, next_path, cursor_param, page_param, page_size_param, page_size, max_pages} for api"
    example: {type: csv, path: /data/landing/orders.csv}
  schedule: {description: Airflow preset or 5-field cron expression, example: "@daily"}
  start_date: {description: first logical date as YYYY-MM-DD, example: "2026-01-01"}
  trino_conn_id: {description: Airflow connection id of the Trino server, example: trino_default}
  retries: {description: "task retries (0 to 5)", example: 2}
  catchup: {description: backfill every interval since start_date, example: false}
  tags: {description: Airflow UI tags, example: [lakehouse]}
  watermark_column: {description: "load only records at or after the highest value already in silver; needs merge and a numeric, date or timestamp column", example: updated_at}
  watermark_param: {description: api query parameter that receives the watermark so the server filters too, example: updated_since}
inputs:
  layout: {type: json, description: "layout from medallion_plan"}
outputs:
  code: {type: python_source, description: the DAG file}
---
# Airflow DAG rendering

## When to use
Once the layers are designed: it produces the Python file to drop into the Airflow `dags` folder.

## When not to use
Never use it to change an existing DAG in place: regenerate the file from the spec instead.

## Interpreting
- The DAG has five tasks in a chain: ensure_tables, load_bronze, quality_gate, bronze_to_silver, refresh_gold.
- quality_gate fails the run when the source produced no rows or a business key is null, before silver is touched.
- The batch id comes from the DAG run id: a retried run deletes and reloads its own bronze rows (and its own silver rows in append mode), so retries never duplicate data.
- With a watermark, each run asks silver for its highest value and keeps only records at or after it (the boundary is re-read on purpose; merge absorbs the duplicates). An empty increment is a normal outcome, not a failure. Without a watermark an empty source fails the run.
- API pagination follows next links only on the same host, and a run that needs more than max_pages pages fails instead of loading partial data.
- Rows are inserted with bound parameters in chunks; no value is ever spliced into SQL text.
- Credentials never appear in the file: APIs and MCP servers use auth_conn_id, Trino uses `trino_conn_id`.
- The MCP reader calls one tool over HTTP with JSON-RPC `tools/call` and expects a JSON payload of records.

## Common mistakes
- Putting a token in the `source` `url` or `query`; the step rejects it.
- Describing a different `source` type than the one that was inspected: pass the same object to both steps.
- Giving the `source` `path` as seen from your laptop instead of from the Airflow worker.
- Setting a watermark on a column that is not in the layout, or with load mode append.
- Omitting the `source` `tool` for an mcp source.
