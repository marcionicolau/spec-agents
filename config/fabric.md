---
root: research_lead
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
  max_depth: 4
  max_agent_runs: 30
  max_delegations: 12
  max_llm_calls: 40
---
# Research assistant for agronomic trials

This file holds only run-wide settings. Each agent lives in `agents/<name>/AGENT.md`:
the frontmatter is its contract, and the body is its working instructions.

```
research_lead (supervisor, router)                 fallback: rules
├── stats_team (supervisor, sequential)
│   ├── statistician (planner, statistics)         fallback: stats_rules
│   └── methods_reviewer (llm, Review schema, grounded)
├── profile_runner (pipeline: exploratory_analysis)
└── notes_digest (pipeline: document_digest)
```

Validate with `python -m agent_fabric.lint --domains ... --agents config`.
