---
name: check_rebuttal
kind: pipeline
version: 1.0.0
domain: legal
description: Validate a drafted rebuttal against its dossier and return accepted and rejected points.
params: {}
inputs:
  rebuttal:
    type: json
    description: Rebuttal object from the rebuttal writer
  dossier:
    type: json
    description: dossier from analyse_case
steps:
- id: check
  component: rebuttal_check
  inputs:
    rebuttal: $inputs.rebuttal
    dossier: $inputs.dossier
outputs:
  report: check.report
---
# Check a rebuttal

## When to use
Run by the quality controller after every draft.

## Procedure
1. `rebuttal_check`: locators, authorities and rationale of every point.
