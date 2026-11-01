---
name: quality_controller
kind: pipeline
pipeline: check_rebuttal
role: Quality controller
goal: Accept only rebuttal points whose locators, authorities and rationale pass the deterministic gate
description: Runs check_rebuttal on the writer's draft against the analyst's dossier.
options:
  # check_rebuttal declares two required json inputs (dossier, rebuttal); case_analyst's and rebuttal_writer's
  # results are both generic json too, so name-based and type-based auto-binding both fail ("ambiguous
  # candidates") - map them to the sub-agents' blackboard paths explicitly instead of relying on either.
  # case_analyst is a planner: its delegation artifact ("@d1") is its wrapper result, not analyse_case's
  # declared "dossier" output - that lives separately at "<path>.dossier" (see _PipelineRunner.execute_and_report).
  # rebuttal_writer is a plain llm agent, so its one artifact already is the Rebuttal itself.
  input_map:
    dossier: case_counsel/case_analyst.dossier
    rebuttal: case_counsel/rebuttal_writer
---
Deterministic gate: no LLM. It receives the dossier and the rebuttal and returns the accepted points, the rejected
ones with their reasons, and the points that need human research.
