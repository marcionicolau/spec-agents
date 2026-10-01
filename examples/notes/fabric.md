---
root: note_taker
skill_dirs: [./skills]          # code-free domain: plain SKILL.md files, no Python package
llm:
  base_url: http://localhost:4000/v1
  api_key: sk-local-dev         # or env LITELLM_API_KEY
  planner_model: local-planner
  interpreter_model: local-writer
  repair_model: local-fast
  temperature: 0.1
  max_correction_attempts: 3
  json_mode: true
budget:
  max_depth: 2
  max_agent_runs: 10
  max_delegations: 6
  max_llm_calls: 15
---
# Meeting-notes assistant (code-free domain demo)

Everything under this folder is Markdown: the domain's skills are `runtime: prompt`
SKILL.md files (their `## Instructions` sections are the prompts), the pipeline is a
`kind: pipeline` spec, and the single agent is a planner over `domains: [notes]`.

```
note_taker (planner, domains: notes, interpret: rules)
└── skills/  summarize_notes · extract_actions · note_digest (pipeline)
```

Run it:  `agent-fabric run examples/notes --input transcript=meeting.txt "Digest this meeting"`
Check it: `agent-fabric lint --agents examples/notes`  or  `python -m agent_fabric.lint --agents examples/notes`
