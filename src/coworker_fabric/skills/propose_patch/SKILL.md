---
name: propose_patch
kind: pipeline
version: 1.0.0
domain: coworker
description: Validate text edits against the files chosen as context and return a unified diff; nothing is written.
params:
  root: {description: repository directory, required: true, example: /home/me/project}
  task: {description: what the change is for, required: true, example: replace the mutable default argument in run}
  focus_files: {description: files the edits touch, required: true, example: [src/app.py]}
  edits: {description: "list of {path, old, new} text replacements", required: true}
  max_changed_lines: {description: size limit for the whole patch, default: null}
inputs: {}
steps:
- id: index
  component: repo_index
  params: {root: $params.root}
- id: pick
  component: context_select
  params: {task: $params.task, focus_files: $params.focus_files}
  inputs: {index: index.index}
- id: patch
  component: patch_propose
  params: {root: $params.root, edits: $params.edits, max_changed_lines: $params.max_changed_lines}
  inputs: {context: pick.context}
outputs: {diff: patch.diff, context: pick.context}
---
# Checked patch

## When to use
After choosing what to change: it proves that every edit applies and that the result still parses.

## Procedure
1. `repo_index`: map the repository.
2. `context_select`: restrict the change to the focus files and their neighbours.
3. `patch_propose`: apply the edits in memory and produce the diff.
