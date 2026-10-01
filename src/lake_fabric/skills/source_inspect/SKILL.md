---
name: source_inspect
version: 2.1.0
domain: lakehouse
category: discovery
description: Infer column names and types of a CSV, JSON, XLSX, API or MCP source from a sample of its records.
runtime: code
params:
  source:
    description: "source description: type (csv, json, xlsx, api or mcp), plus path/sheet/delimiter/encoding for files, url/method/query/auth_conn_id/timeout for api and mcp, records_path for JSON payloads, tool/arguments for mcp, pagination {mode next_link|cursor|page, next_path, cursor_param, page_param, page_size_param, page_size, max_pages} for api"
    example: {type: csv, path: /data/landing/orders.csv}
  sample_rows: {description: how many records to read for type inference, example: 200}
inputs:
  sample:
    type: json
    required: false
    description: example records (list of objects); mandatory for api and mcp sources
outputs:
  schema: {type: json, description: "{columns: [{name, source_name, type, null_rate}]} with snake_case names"}
---
# Source inspection

## When to use
The first step of every ingestion: it turns an unknown source into a typed column list that the medallion design needs.

## When not to use
The schema is already known and fixed; then supply it directly. API and MCP sources cannot be read here: bind a `sample` of records.

## Interpreting
- `columns` lists the sanitised `name` used in every table, the original `source_name` and the inferred `type`.
- Types are varchar, bigint, double, boolean, date or timestamp. A column that mixes kinds falls back to varchar.
- A `null_rate` of 1.0 means the column was empty in the sample, so its type is a guess.
- Fewer than 20 sampled rows produce a warning: the types may change with more data.

## Common mistakes
- Pointing `source` `path` at a file with the wrong extension for `source_type`.
- Forgetting `source` records_path when the JSON document wraps the records in an envelope.
- Using identifier-like columns with leading zeros as numbers: they stay varchar on purpose.
