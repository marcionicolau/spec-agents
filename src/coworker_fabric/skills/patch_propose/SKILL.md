---
name: patch_propose
version: 1.0.0
domain: coworker
category: change
description: Validate proposed text edits against the real files and produce a unified diff without touching the disk.
params:
  root: {description: repository directory, example: /home/me/project}
  edits:
    description: "list of {path, old, new}; old is the exact text to replace and must occur exactly once"
    example: [{path: src/app.py, old: "def run(x=[]):", new: "def run(x=None):"}]
  max_changed_lines: {description: reject patches that change more lines than this, example: 200}
inputs:
  context: {type: json, required: false, description: selection from context_select; edits are limited to these files}
outputs:
  diff: {type: text, description: unified diff of all edits}
---
# Patch proposal

## When to use
A model or person suggests a change and you need proof that it applies cleanly and leaves valid Python.

## When not to use
Creating new files or renaming: only edits of existing files are supported. Nothing is ever written to disk.

## Interpreting
- Success means every `old` text was found exactly once, the files still parse and the size is within `max_changed_lines`. It does not mean the change is correct or that tests pass.
- Failures are located per edit: old_text_not_found includes the closest line, old_text_ambiguous asks for more surrounding lines.
- Apply the diff with your usual tooling after review, then run the tests.

## Common mistakes
- Retyping the old text from memory instead of copying it from the file, including indentation.
- Bundling unrelated changes in one patch; split them.
- Editing files outside the selected context; the step rejects them.
