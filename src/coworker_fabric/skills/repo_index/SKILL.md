---
name: repo_index
version: 1.0.0
domain: coworker
category: discovery
description: Index a code repository - files, sizes in tokens, Python symbols with complexity and the import graph.
params:
  root: {description: repository directory as seen by the machine running the step, example: /home/me/project}
  include: {description: glob patterns relative to the root; default is Python files, example: ["src/**/*.py"]}
  exclude_dirs: {description: "extra directory names to skip (venvs, caches and .git are always skipped)", example: [migrations]}
  max_files: {description: cap on indexed files, example: 2000}
  max_file_kb: {description: files larger than this are skipped, example: 512}
outputs:
  index: {type: json, description: "files (path, lines, tokens, symbols, imports) and import edges"}
---
# Repository index

## When to use
The first step of any pair-programming task: nothing else can choose context without it.

## When not to use
The question is about a single file whose path you already know and you only need to read it.

## Interpreting
- `n_edges` counts import links between indexed files; 0 in a large repo suggests the roots or packages are not what you expected.
- `largest` shows the files that will dominate a token budget.
- `parse_errors` lists Python files that do not parse; they are indexed without symbols.
- Token counts are estimates (characters divided by four), good enough to budget a prompt.

## Common mistakes
- Pointing `root` at a subdirectory, which hides the imports that cross it.
- Using absolute or `..` patterns in `include`; the step rejects them.
- Using a root outside the allowed directories (the working directory by default, or those listed in the COWORKER_ALLOWED_ROOTS environment variable); the step rejects it.
