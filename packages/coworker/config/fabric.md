---
root: pair_programmer
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
  max_llm_calls: 25
---
# Coworker (pair programming)

Helps to improve code: it chooses which files belong in the context, reviews them, and checks patch proposals
without ever writing to disk. Each agent lives in `agents/<name>/AGENT.md`.

```
pair_programmer (supervisor, router)
├── context_scout (planner, coworker)   index + context selection + review of the chosen files
├── code_critic (llm, Critique schema)  turns the findings into prioritised suggestions
└── patch_author (planner, coworker)    proposes edits; the checker validates them and returns a diff
```

Validate with `python -m agent_fabric.lint --domains coworker_fabric.domain:register --agents packages/coworker/config
--schemas coworker_fabric.schemas:SCHEMAS --strict`.
