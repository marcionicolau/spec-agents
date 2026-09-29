---
name: context_pack
version: 1.0.0
domain: coworker
category: selection
description: Assemble the selected files into one Markdown bundle ready to paste into a prompt.
params:
  max_chars_per_file: {description: files longer than this are cut with a marker, example: 20000}
inputs:
  context: {type: json, description: selection from context_select}
outputs:
  bundle: {type: text, description: Markdown with one fenced block per file and the reason it was chosen}
---
# Context bundle

## When to use
After `context_select`, when a model or a person needs the actual code.

## When not to use
Only the list of files is needed; the selection already has it.

## Interpreting
- `truncated` names files that were cut; the model must not assume it saw their end.
- The bundle is read from disk at this moment: if a file changed since indexing, the bundle shows the new content.

## Common mistakes
- Packing a selection made from an old index; the step fails when a selected file no longer exists.
