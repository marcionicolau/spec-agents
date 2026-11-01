---
name: authority_select
version: 1.1.0
domain: legal
category: retrieval
description: Pick laws and precedents from a curated local corpus for each refutable point, with a confidence level.
runtime: code
params:
  corpus_path:
    description: JSONL of curated authorities
    example: /cases/authorities.jsonl
  top_k:
    description: authorities kept per point
    example: 3
  min_score:
    description: minimum BM25 score to keep an authority
    example: 1.0
  lang:
    description: language of rationale and warning text, "pt-BR" (default) or "en-US"
    example: pt-BR
inputs:
  points:
    type: json
    description: points from argument_map
outputs:
  authorities:
    type: json
    description: point_id -> list of id, ref, court, binding, score, confidence, rationale
---
# Authority selection

## When to use
After the argument map: a counter-argument is only allowed when an authority sustains it.

## Interpreting
- `confidence` is high for binding authorities (súmula vinculante, repetitive theses) and medium otherwise.
- needs_research lists points with no authority: a lawyer must research them; the writer may not argue them.
- Only the curated corpus is searched, so every id is something a person already checked.

## Common mistakes
- Filling the corpus with unreviewed web results: the confidence gate then means nothing.
