---
name: process_ingest
version: 1.0.0
domain: legal
category: ingestion
description: Read an eproc case download (one PDF or TXT per document) into a paginated, line-numbered record.
runtime: code
params:
  root:
    description: folder with the downloaded case documents
    example: /cases/5001234-56.2025.8.21.0021
  case_id:
    description: case number used in every report
    example: 5001234-56.2025.8.21.0021
  kind_map:
    description: extra eproc document codes mapped to kinds
    example:
      OFIC: outro
  phases:
    description: phase overrides per document id
    example:
      ev12/DEPOIM1: judicial
  max_docs:
    description: maximum documents to read
    example: 500
inputs: {}
outputs:
  case:
    type: case
    description: case_id and docs with doc_id, kind, phase and pages of numbered lines
---
# Process ingest

## When to use
First step of every case analysis: it fixes the document ids, pages and line numbers that all later citations use.

## Interpreting
- doc_id is `ev<event>/<CODE><n>`, built from file names like `EVENTO12_DEPOIM1.pdf`. Locators everywhere else
  are `<doc_id> p.<page> l.<line>`.
- `phases` counts documents per phase: `inquerito`, `judicial`, `pericial`; `desconhecida` means the text gave no
  clue and the phase should be set by hand, because the consistency rules depend on it.
- A warning about a missing text layer means a scanned PDF: run OCR first, otherwise its evidence is invisible.

## Common mistakes
- Pointing `root` at a single PDF of the whole case: split the download per document first.
- Ignoring `desconhecida` phases: inquiry_only and `retraction` rules then miss cases.
