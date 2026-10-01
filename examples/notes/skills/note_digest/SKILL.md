---
name: note_digest
kind: pipeline
version: 1.0.0
domain: notes
description: Full meeting digest - summary plus extracted decisions and action items.
params:
  tone: {description: "summary tone", required: false, default: neutral}
  default_owner: {description: "fallback action owner", required: false, default: unassigned}
inputs:
  transcript: {type: text, description: the meeting transcript}
steps:
  - {id: sum, component: summarize_notes, params: {tone: $params.tone}}
  - {id: act, component: extract_actions, params: {default_owner: $params.default_owner}}
outputs: {summary: sum.summary, actions: act.actions}
---
# Note digest

## When to use
The standard "digest this meeting" request: one transcript in, summary + actions out.

## Procedure
1. `summarize_notes` gives the faithful short summary.
2. `extract_actions` lists decisions and action items from the same transcript.

## Interpreting
`summary` is prose; `actions` is JSON with `actions` (owner/task/due) and `decisions` lists.
