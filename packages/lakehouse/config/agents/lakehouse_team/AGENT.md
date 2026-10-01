---
name: lakehouse_team
kind: supervisor
strategy: sequential
synthesize: false
sub_agents: [dag_engineer, dag_reviewer]
role: Lakehouse ingestion team
description: Turns a data source into a verified Airflow DAG that loads bronze, silver and gold tables in Trino, then reviews it.
---
Run `dag_engineer` first: it produces the DAG and the table design. Then `dag_reviewer` judges the result.
The review sees the engineer's full output; a `rejected` verdict means the DAG must not be deployed.
