---
name: context_select
version: 1.1.0
domain: coworker
category: selection
description: Choose the files worth reading for a task within a token budget, using focus files, import links and task terms.
runtime: code
params:
  task: {description: "what you want to do, in a sentence with concrete names", example: make the executor skip dependents of failed steps}
  focus_files: {description: "files you already know are central, relative to the root", example: [src/agent_fabric/executor.py]}
  token_budget: {description: maximum tokens of selected files, example: 8000}
  max_files: {description: maximum number of selected files, example: 12}
  hops: {description: "how many import links away from the focus files to look, 0 to 3", example: 1}
  include_tests: {description: also select the tests that belong to the focus files, example: true}
  relative_cutoff: {description: "drop files scoring below this fraction of the best non-focus file, 0 to 1", example: 0.5}
  partial_files: {description: "large files that match only in places contribute just their matching symbols (line ranges)", example: true}
inputs:
  index: {type: json, description: index from repo_index}
outputs:
  context: {type: json, description: "root, task and the selected files with score and reasons"}
---
# Context selection

## When to use
Before reading or changing code: it decides what goes into the prompt so that the budget is spent on relevant files.

## When not to use
The whole repository fits in the budget; then read everything.

## Interpreting
- Every selected file has `reasons`: it is a focus file, an import neighbour, the test of a focus file, or it matches task terms.
- A large file may be selected only in part: `ranges` lists the line ranges and `symbols` the functions or classes inside them. The rest of that file is not in the context, so do not assume anything about it.
- Focus files always come first, and always whole. The rest are added by score until `token_budget` or `max_files` is reached.
- A warning about relevant files that did not fit means the picture is incomplete: raise the budget or narrow the focus.
- Words that occur in most files count little; rare words count a lot. Test files rank lower unless the task mentions tests or they belong to a focus file.
- Scores are ranks, not probabilities. Compare them only within one selection.

## Common mistakes
- Leaving `focus_files` empty and describing the task with vague words: the step asks for concrete names.
- Focus files that alone exceed `token_budget`.
- Raising `hops` to 3 in a densely connected repo: it pulls in most of the code.
