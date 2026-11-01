---
name: claim_verify
version: 1.1.0
domain: legal
category: verification
description: Quality control that keeps only claims whose quote is really at the cited document, page and lines.
runtime: code
params:
  min_similarity:
    description: minimum fuzzy match between quote and cited lines, 0.5 to 1
    example: 0.85
  line_slack:
    description: lines of drift tolerated around the cited range
    example: 1
  lang:
    description: language of warning text, "pt-BR" (default) or "en-US"
    example: pt-BR
inputs:
  case:
    type: case
    description: record from process_ingest
  claims:
    type: json
    description: claims from claim_extract
outputs:
  verified:
    type: json
    description: claims that resolved, with kind and phase of their document
  rejected:
    type: json
    description: claims that failed, each with its reason
---
# Claim verification

## When to use
Always after `claim_extract` and before any reasoning: nothing downstream sees an unverified claim.

## Interpreting
- `reasons` counts failures: bad_shape, bad_locator, out_of_range, quote_not_found.
- Many quote_not_found means the model paraphrased; many bad_locator means it ignored the prefixes. A warning
  appears above 30% rejection: rerun the extraction rather than lowering `min_similarity`.

## Common mistakes
- Lowering `min_similarity` below 0.8 to rescue claims: that readmits paraphrases as quotes.
