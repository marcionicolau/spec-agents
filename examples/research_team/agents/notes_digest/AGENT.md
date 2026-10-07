---
name: notes_digest
kind: pipeline
pipeline: document_summary
inputs: [notes]
role: Field-notes digester
description: "Digests field notes: length, key terms and a faithful summary."
---
Runs the `document_summary` pipeline on the field notes: deterministic stats and
keywords, then a model-written summary steered by the question.
