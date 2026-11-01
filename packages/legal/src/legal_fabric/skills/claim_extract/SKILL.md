---
name: claim_extract
version: 1.1.0
domain: legal
category: extraction
description: LLM extraction of factual claims from the evidence bundle, each with speaker, facts, elements and locator.
runtime: prompt
prompt:
  model: local-extract
  temperature: 0.0
  grounding: true
inputs:
  bundle:
    type: text
    description: bundle from evidence_segment
    constraints:
      min_chars: 50
outputs:
  claims:
    type: json
    description: list of claims with id, loc, quote, speaker, role, party, about, facts, supports
---
# Claim extraction

## When to use
Between `evidence_segment` and `claim_verify`; its output is never used before verification.

## Interpreting
- Claims are candidates. `claim_verify` drops any whose quote is not at the cited lines.

## Instructions
Extract the factual statements from the case documents below. Answer a JSON object with one key, "claims", a list.
Each claim has:
- "id": c1, c2, ...
- "loc": "Evento <n>, <code> p.<page> l.<first>-<last>" copied from the ### header and the [p.N l.M] prefixes
- "quote": the exact words of those lines (at least 8 characters, no paraphrase)
- "speaker": who says it, as named in the document; "role": vitima, testemunha, policial, reu, perito or documento
- "party": acusacao when it helps the accusation, defesa when it helps the defence, otherwise neutro
- "about": a short name for the episode, the same for every claim about the same episode (default "fato")
- "facts": only slots the quote states: time, place, actor, action, object, weapon, clothing, quantity
- "supports": ids from the ELEMENTOS line that this claim helps to prove; empty when none

Do not invent speakers, slots, numbers or locators. If a document says nothing factual, skip it.
Keep "claims" a JSON list: when the record yields few statements, emit a shorter list — never prose,
commentary or a nested object in its place.

{inputs.bundle}
