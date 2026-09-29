---
name: keywords
version: 1.0.0
domain: text
category: extraction
description: Most frequent content words after stop-word removal.
params:
  top_k: {description: how many terms to return, example: 10}
  min_length: {description: minimum word length, example: 4}
  extra_stopwords:
    description: additional words to ignore
    example: [wheat]
inputs:
  text:
    type: text
    description: document text
    constraints: {min_chars: 20}
outputs:
  terms: {type: json, description: list of top terms}
---
# Keyword extraction

## When to use
Find what a document is about: the most frequent content words after stop-word removal.

## Interpreting
Counts are raw frequencies. With short texts, ties are common, so do not over-read the ranking.
Use `extra_stopwords` to remove words that are frequent but uninformative in the domain
(e.g. "plot", "field").

## Common mistakes
- Setting `min_length` so high that no words qualify.
- Expecting multi-word phrases: only single words are extracted.
