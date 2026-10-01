---
root: lakehouse_team
llm:
  base_url: http://localhost:4000/v1
  api_key: sk-local-dev            # or env LITELLM_API_KEY
  planner_model: local-planner
  interpreter_model: local-writer
  repair_model: local-fast
  temperature: 0.1
  max_correction_attempts: 3
  json_mode: true
  pydantic_ai_output_mode: prompted
budget:
  max_depth: 3
  max_agent_runs: 10
  max_delegations: 6
  max_llm_calls: 20
---
# Lakehouse ingestion assistant

Generates Airflow DAGs that land a source (CSV, JSON, XLSX, API or MCP tool) in Trino/Iceberg tables organised as
bronze, silver and gold. Each agent lives in `agents/<name>/AGENT.md`.

```
lakehouse_team (supervisor, sequential)
├── dag_engineer (planner, lakehouse)      inspects, designs, renders and checks the DAG
└── dag_reviewer (llm, DagReview schema)   reviews the design and warnings
schema_designer (planner, lakehouse)       design only, no code (use as root for a dry run)
```

Validate with `python -m agent_fabric.lint --domains lake_fabric.domain:register --agents packages/lakehouse/config
--schemas lake_fabric.schemas:SCHEMAS --strict`.
