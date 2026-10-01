---
name: improve_code
kind: pipeline
version: 1.0.0
domain: coworker
description: Index a repository, pick the context for a task within a token budget, bundle it and review it statically.
params:
  root: {description: repository directory, required: true, example: /home/me/project}
  task: {description: what you want to improve, required: true, example: simplify the pipeline executor}
  focus_files: {description: files known to be central, default: null}
  token_budget: {description: maximum tokens of selected files, default: null}
  max_files: {description: maximum selected files, default: null}
  hops: {description: import links to follow from focus files, default: null}
inputs: {}
steps:
- id: index
  component: repo_index
  params: {root: $params.root}
- id: pick
  component: context_select
  params: {task: $params.task, focus_files: $params.focus_files, token_budget: $params.token_budget, max_files: $params.max_files, hops: $params.hops}
  inputs: {index: index.index}
- id: pack
  component: context_pack
  inputs: {context: pick.context}
- id: review
  component: code_review
  inputs: {context: pick.context}
outputs: {bundle: pack.bundle, findings: review.findings, context: pick.context}
---
# Improve code with a pair

## When to use
Start of a refactoring or clean-up session: what to read, and what is worth changing in it.

## Procedure
1. `repo_index`: map files, symbols and imports.
2. `context_select`: spend the token budget on the files that matter for the task.
3. `context_pack`: turn the selection into a bundle the model can read.
4. `code_review`: list concrete findings in exactly those files.

## Interpreting
Start from the findings of highest severity that fall in the focus files, and use the bundle as the only source for code.
