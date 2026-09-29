---
name: text_stats
version: 1.0.0
domain: text
category: descriptive
description: Word and sentence counts, average word length and lexical diversity.
params:
  lowercase: {description: lower-case words before counting, example: true}
inputs:
  text:
    type: text
    description: document text
    constraints: {min_chars: 1}
---
# Text statistics

## When to use
Describe the size and vocabulary richness of a document before summarising or comparing it.

## Interpreting
- `lexical_diversity` is the share of distinct words. Values near 1 are typical of short texts; long
  technical reports usually fall between 0.3 and 0.5.
- Statistics for texts under ~50 words are unstable. The component warns when that happens.
