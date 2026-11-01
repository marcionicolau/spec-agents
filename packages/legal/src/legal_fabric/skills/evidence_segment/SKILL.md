---
name: evidence_segment
version: 1.0.0
domain: legal
category: preparation
description: Render testimony, reports and pleadings as a line-numbered text bundle the claim extractor cites from.
runtime: code
params:
  kinds:
    description: document kinds to include
    example:
    - depoimento
    - interrogatorio
    - laudo
  max_chars:
    description: size cap of the bundle
    example: 60000
inputs:
  case:
    type: case
    description: record from process_ingest
  charges:
    type: json
    description: charges from crime_classify
outputs:
  bundle:
    type: text
    description: element ids, then each document with [p.N l.M] line prefixes
---
# Evidence segment

## When to use
Before `claim_extract`: the prefixes are what lets the model cite page and line instead of paraphrasing.

## Interpreting
- `left_out` lists documents that did not fit `max_chars`; their content is invisible to the extractor. Raise the
  cap, narrow `kinds`, or run the extraction per document for long cases.

## Common mistakes
- Including sentences or pleadings when the goal is to test the evidence: they repeat claims without being evidence.
