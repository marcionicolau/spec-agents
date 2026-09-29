---
name: notes_digest
kind: pipeline
pipeline: document_digest
inputs: [notes]
role: Field-notes digester
description: Summarises field notes by length and key terms.
---
Runs the `document_digest` pipeline on the field notes. No LLM is involved.
