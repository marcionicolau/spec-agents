---
name: crime_classify
version: 1.2.0
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
  crimes_path:
    description: crimes YAML override; the packaged ontology (data/crimes.yaml) when unset
    example: /firm/crimes.yaml
  lang:
    description: language of rationale and warning text, "pt-BR" (default) or "en-US"
    example: pt-BR
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
- A charge in `unknown` has no elements in the ontology, so nothing is checked for it until they are added — either
  to `data/crimes.yaml` or to a firm's own copy pointed to by `crimes_path`. The YAML format needs no code change.
- The `rationale` of each charge says where it came from and why elements are checked one by one.

## Common mistakes
- Relying on detection for amended charges (aditamento): add the new article to `articles`.
- Adding a crime type under a law `_LAW_CODES` does not recognise (only `CP` and `L11343` are detected in free
  text): it still works, but only via `articles` given by hand, never from automatic detection in the denúncia.
