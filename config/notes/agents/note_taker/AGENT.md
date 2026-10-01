---
name: note_taker
kind: planner
backend: fabric
domains: [notes]
inputs: [transcript]
interpret: rules
role: Meeting-notes assistant
description: Summarises meeting transcripts and extracts decisions and action items.
---
Prefer the `note_digest` pipeline shape for "digest"/"summarise" requests: `summarize_notes`
first, then `extract_actions` on the same `transcript`. Add only the steps the question needs.
