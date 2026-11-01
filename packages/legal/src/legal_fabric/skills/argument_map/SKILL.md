---
name: argument_map
version: 1.1.0
domain: legal
category: analysis
description: Rank each side's points as strong or weak from evidence and anomalies, and list refutation targets.
runtime: code
params:
  min_speakers_strong:
    description: distinct judicial speakers needed for a strong accusation point
    example: 2
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
  anomalies:
    type: json
    description: anomalies from consistency_check
outputs:
  points:
    type: json
    description: point_id, side, statement, strength, evidence, rationale per point
---
# Argument map

## When to use
After the consistency check, to decide where the petition attacks and where it should not spend effort.

## Interpreting
- One accusation point per charge element; `refutation_targets` are the weak ones.
- Defence points come from anomalies (they `attacks` an accusation point) and from defence claims, which are strong
  only when another speaker corroborates them.
- `strength` is a rule outcome; the `rationale` lists the counts that produced it.

## Common mistakes
- Treating a strong accusation point as refutable by argument alone: it needs new evidence.
