---
name: rebuttal_check
version: 1.0.0
domain: legal
category: verification
description: Gate a drafted rebuttal - locators must exist, authorities must be selected, each point must explain itself.
runtime: code
params:
  min_rationale_chars:
    description: shortest acceptable rationale paragraph
    example: 200
  max_rationale_chars:
    description: longest acceptable rationale paragraph
    example: 1500
inputs:
  rebuttal:
    type: json
    description: Rebuttal object from the rebuttal writer
  dossier:
    type: json
    description: dossier from dossier_build
outputs:
  report:
    type: json
    description: accepted points, rejected points with reasons, points needing research
---
# Rebuttal check

## When to use
After the writer, before anything reaches the lawyer: it is the final quality control.

## Interpreting
- Reasons: unknown_target, bad_locator, no_authority, authority_not_selected, rationale_not_one_paragraph.
- Rejected points go back to the writer with their reasons; never hand them to the lawyer as accepted.

## Common mistakes
- Passing the case instead of the dossier: the check needs the selected authorities per point.
