---
name: draft_edits
version: 1.0.0
domain: coworker
category: change
description: Draft the smallest {path, old, new} text edits for a task from a context bundle, for patch_propose to validate.
runtime: prompt
prompt: {grounding: true}
params:
  task: {description: "what the change must achieve, in one sentence", required: true, example: raise ValueError on an empty input to mean}
inputs:
  bundle: {type: text, description: code bundle from context_pack}
outputs:
  edits: {type: json, description: "list of {path, old, new} replacements, one object per edit"}
---
# Draft edits

## When to use
Before `patch_propose` when the edits are not known yet: the model reads the code bundle and drafts the
exact replacements; `patch_propose` then proves they apply and still parse.

## When not to use
The edits are already decided: pass them to `patch_propose` directly and skip the model.

## Instructions
Draft the smallest change that satisfies this task: {params.task}

Read the code bundle below and answer a JSON object `{{"edits": [{{"path": ..., "old": ..., "new": ...}}]}}`:

- `path` must be one of the file paths shown in the bundle.
- `old` is copied verbatim from the bundle, including indentation and comments, and must occur exactly once
  in that file — add neighbouring lines when a single line is not unique.
- `new` is the replacement text; keep the diff as small as the task allows.
- Do not invent files, functions or lines that are not in the bundle.

Bundle:
{inputs.bundle}

## Interpreting
`edits` is a draft only: `patch_propose` decides whether each `old` matches uniquely and the result parses.

## Common mistakes
- Paraphrasing `old` instead of copying it — whitespace and indentation must match the bundle exactly.
- Editing a file that is not part of the bundle.
- Answering with prose instead of the JSON object.
