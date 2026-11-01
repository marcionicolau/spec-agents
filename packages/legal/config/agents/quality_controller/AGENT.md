---
name: quality_controller
kind: pipeline
pipeline: check_rebuttal
role: Quality controller
goal: Accept only rebuttal points whose locators, authorities and rationale pass the deterministic gate
description: Runs check_rebuttal on the writer's draft against the analyst's dossier.
---
Deterministic gate: no LLM. It receives the dossier and the rebuttal and returns the accepted points, the rejected
ones with their reasons, and the points that need human research.
