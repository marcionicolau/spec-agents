---
name: document_digest
kind: pipeline
version: 1.0.0
domain: text
description: Text statistics plus top keywords of a document.
params:
  top_k: {description: number of keywords, default: 8}
inputs:
  text: {type: text, description: document to digest}
steps:
- {id: stats, component: text_stats}
- id: kw
  component: keywords
  params: {top_k: $params.top_k}
outputs: {terms: kw.terms}
---
# Document digest

## When to use
A quick overview of a report, abstract or field note.

## Procedure
1. `text_stats`: size and vocabulary.
2. `keywords`: top `top_k` terms, exposed as `terms`.
