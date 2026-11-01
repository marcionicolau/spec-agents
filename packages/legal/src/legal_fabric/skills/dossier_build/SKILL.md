---
name: dossier_build
version: 1.1.0
domain: legal
category: packaging
description: Bundle charges, claims, anomalies, points, authorities and page sizes into one dossier for writer and checker.
runtime: code
params:
  lang:
    description: language the rebuttal writer is instructed to answer in, "pt-BR" (default) or "en-US"
    example: pt-BR
inputs:
  case:
    type: case
    description: record from process_ingest
  charges:
    type: json
    description: charges from crime_classify
  claims:
    type: json
    description: verified claims
  anomalies:
    type: json
    description: anomalies from consistency_check
  points:
    type: json
    description: points from argument_map
  authorities:
    type: json
    description: authorities from authority_select
outputs:
  dossier:
    type: json
    description: everything the rebuttal needs, without document text
---
# Dossier

## When to use
Last step of the analysis: the rebuttal writer reads it and `rebuttal_check` validates against it.

## Interpreting
- page_sizes lets locators be checked without shipping the record to the writer.
- `rules` repeats the writing rules, including the language directive from `lang`, so they travel with the data.
  It is the first key after `case_id` on purpose: a long dossier gets truncated from the end before an LLM step
  sees it, and a rule that silently disappeared is worse than one read slightly out of order.
