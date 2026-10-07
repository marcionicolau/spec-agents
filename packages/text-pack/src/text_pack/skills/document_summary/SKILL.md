---
name: document_summary
kind: pipeline
version: 1.0.0
domain: text
description: Text statistics, top keywords and a faithful LLM-written summary of a document.
params:
  top_k: {description: number of keywords, default: 8}
  max_words: {description: summary length cap, default: 150}
inputs:
  text: {type: text, description: document to digest}
steps:
- {id: stats, component: text_stats}
- id: kw
  component: keywords
  params: {top_k: $params.top_k}
- id: sum
  component: summarize_text
  params: {max_words: $params.max_words}
outputs: {terms: kw.terms, summary: sum.summary}
---
# Document summary

## When to use
A grounded digest of a document — a chat export, report or field note — that must
say what was decided or who owns what. Unlike `document_digest`, the last step is
a model-written `summary` and needs an LLM backend.

## Procedure
1. `text_stats` and `keywords` give the deterministic overview.
2. `summarize_text` reads the raw text and writes the objective-driven `summary`.

## Interpreting
`terms` are raw frequencies; `summary` is grounded prose — quote it, do not extend it.
