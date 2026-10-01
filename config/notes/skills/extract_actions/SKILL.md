---
name: extract_actions
version: 1.0.0
domain: notes
category: text
description: Extract decisions and action items (owner, task, due) from a meeting transcript as JSON.
runtime: prompt
prompt: {grounding: true}
params:
  default_owner: {description: "owner used when the transcript names none", required: false,
                  default: unassigned, example: team}
inputs:
  transcript: {type: text, description: the meeting transcript, constraints: {min_chars: 20}}
outputs:
  actions: {type: json}
---
# Extract actions

## When to use
After `summarize_notes`, when the question asks who promised what, what was decided, or what
happens next.

## Instructions
From the transcript below, extract the decisions and action items. Reply with a JSON object:

{{"actions": [{{"owner": "...", "task": "...", "due": "..."}}], "decisions": ["..."]}}

Use "{params.default_owner}" when the transcript does not name an owner and null for `due`
when no date is given. Do not invent owners, tasks or dates.

Objective: {objective}

Transcript:
{inputs.transcript}

## Interpreting
`actions` is a JSON object: `actions` is a list of {owner, task, due}, `decisions` a list of
strings. Empty lists mean nothing was agreed.

## Common mistakes
- Guessing an owner instead of using `default_owner`.
- Returning prose instead of the JSON object.
