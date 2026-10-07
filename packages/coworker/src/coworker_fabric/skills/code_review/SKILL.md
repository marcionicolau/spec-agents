---
name: code_review
version: 2.0.0
domain: coworker
category: review
description: Static review of the selected Python files - complexity, long functions, risky exception handling, unused imports.
runtime: code
params:
  max_function_lines: {description: functions longer than this are flagged, example: 60}
  max_complexity: {description: cyclomatic complexity above this is flagged, example: 10}
  max_params: {description: functions with more parameters are flagged, example: 6}
  disable: {description: "rule names to ignore, for example todo_comment or print_call", example: [todo_comment]}
  max_findings: {description: "findings beyond this are cut, most severe first", example: 100}
inputs:
  context: {type: context, description: selection from context_select}
outputs:
  findings: {type: json, description: "list of findings with path, line, rule, severity, message and suggestion"}
---
# Code review

## When to use
To find concrete, verifiable improvements in the files chosen as context.

## When not to use
Style or formatting questions; a formatter and linter do that better. Non-Python files are ignored.

## Interpreting
- Severity `error` means a likely defect (mutable default argument, eval or exec, syntax error). `warning` is a maintainability risk. `info` is a preference.
- Rules are heuristics. unused_import can be wrong for imports that exist only for side effects or re-export.
- high_complexity and long_function usually point at the same function: fix one refactor, not two.
- Report only findings that appear in the result; never invent line numbers.

## Common mistakes
- Binding anything into `context` but the `context` output of `context_select`, and expecting a `bundle` output: the step emits `findings`; the bundle comes from `context_pack`.
- Treating missing_return_annotation as urgent in code that does not use type hints.
- Reviewing files that were not selected as context.
