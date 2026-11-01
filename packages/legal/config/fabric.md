---
root: case_counsel
llm:
  base_url: http://localhost:4000/v1
  api_key: sk-local-dev            # or env LITELLM_API_KEY; keep case data on local models
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
  max_llm_calls: 30
---
# Legal (criminal case pair)

Works a criminal case with a lawyer: reads the record, finds contradictions and thin evidence, and drafts rebuttal
points that cite the record by page and line and rest on authorities a person has curated. Nothing is filed.

```
case_counsel (supervisor, router)
├── case_analyst (planner, legal)        analyse_case: ingest → extract → verify → rules → points → authorities
├── rebuttal_writer (llm, Rebuttal)      argues only from the dossier, one rationale paragraph per point
└── quality_controller (pipeline)        check_rebuttal: locators, authorities and rationale gate
```

Validate with `python -m agent_fabric.lint --domains legal_fabric.domain:register --agents packages/legal/config
--schemas legal_fabric.schemas:SCHEMAS --strict`.
