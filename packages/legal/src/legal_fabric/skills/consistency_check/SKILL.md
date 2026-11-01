---
name: consistency_check
version: 1.1.0
domain: legal
category: analysis
description: Symbolic rules over verified claims - contradictions, retractions, missing or inquiry-only elements.
runtime: code
params:
  time_tolerance_min:
    description: minutes of disagreement on time still treated as consistent
    example: 30
  outlier_z:
    description: z-score above which a speaker's conflict count is flagged
    example: 1.5
  identity_slots:
    description: fact slots whose conflicts count as high severity
    example:
    - actor
    - weapon
    - clothing
  lang:
    description: language of rationale text, "pt-BR" (default) or "en-US"
    example: pt-BR
inputs:
  claims:
    type: json
    description: verified claims from claim_verify
  charges:
    type: json
    description: charges from crime_classify
outputs:
  anomalies:
    type: json
    description: id, rule, severity, element, claims, locators and rationale per anomaly
---
# Consistency check

## When to use
After verification, to find where testimony, documents and proofs disagree and which elements are thinly proved.

## Interpreting
- slot_conflict: two speakers disagree on the same fact; high when it touches identification.
- `retraction`: the same speaker changed version between inquiry and court.
- missing_element: no verified claim supports an element; inquiry_only: only inquiry-phase support.
- single_source: one speaker carries an element alone. outlier_speaker is statistical, not proof of lying.
- Every anomaly's `rationale` names the locators and why the rule fired.

## Common mistakes
- Feeding raw `claim_extract` output: the rules need `phase`, which only verified claims carry.
