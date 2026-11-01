---
name: crime_classify
version: 1.0.0
domain: legal
category: classification
description: Find the charged articles in the accusation and expand each into the elements the prosecution must prove.
runtime: code
params:
  source_kinds:
    description: document kinds to scan for article citations
    example:
    - denuncia
  articles:
    description: charges given by hand as LAW:ARTICLE
    example:
    - CP:157
inputs:
  case:
    type: case
    description: record from process_ingest
outputs:
  charges:
    type: json
    description: charge_id, name, elements, found_at and rationale per charge
---
# Crime classification

## When to use
Right after ingest: the elements of each charge are the checklist for the consistency rules and the argument map.

## Interpreting
- Each charge lists found_at locators in the accusation; a charge with none came from `articles`.
- A charge in `unknown` has no elements in the ontology, so nothing is checked for it until they are added.
- The `rationale` of each charge says where it came from and why elements are checked one by one.

## Common mistakes
- Relying on detection for amended charges (aditamento): add the new article to `articles`.
