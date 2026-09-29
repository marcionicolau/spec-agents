---
name: dag_check
version: 1.0.0
domain: lakehouse
category: verification
description: Static safety and structure check of a generated Airflow DAG (imports, calls, secrets, required tasks).
params:
  extra_imports: {description: additional top-level modules the DAG may import, example: []}
inputs:
  code: {type: python_source, description: DAG source to verify}
---
# DAG check

## When to use
Always as the last step: generated code is not accepted until it passes.

## When not to use
It does not run the DAG or reach Trino; use an Airflow test environment for that.

## Interpreting
- A failure lists every problem with its line: disallowed imports, `eval`/`exec`/subprocess calls, destructive SQL, hardcoded secrets, a missing `@dag` or a missing medallion task.
- Warnings note risky settings such as `catchup` enabled or zero retries.
- A pass means the file parses and matches the expected structure, nothing more.

## Common mistakes
- Adding `extra_imports` to silence a finding instead of fixing the generator input.
- Editing the generated code by hand and re-checking it; regenerate instead.
