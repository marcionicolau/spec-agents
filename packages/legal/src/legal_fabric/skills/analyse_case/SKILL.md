---
name: analyse_case
kind: pipeline
version: 1.1.0
domain: legal
description: Ingest a criminal case, extract and verify claims, check consistency, map points and pick authorities.
params:
  root:
    description: folder with the downloaded case documents
    required: true
    example: /cases/5001234-56
  corpus_path:
    description: JSONL of curated authorities
    required: true
    example: /cases/authorities.jsonl
  case_id:
    description: case number
    default: null
  articles:
    description: charges given by hand as LAW:ARTICLE
    default: null
  lang:
    description: language of rationale and warning text, "pt-BR" (default) or "en-US"
    default: pt-BR
inputs: {}
steps:
- id: ingest
  component: process_ingest
  params:
    root: $params.root
    case_id: $params.case_id
    lang: $params.lang
- id: classify
  component: crime_classify
  params:
    articles: $params.articles
    lang: $params.lang
  inputs:
    case: ingest.case
- id: segment
  component: evidence_segment
  params:
    lang: $params.lang
  inputs:
    case: ingest.case
    charges: classify.charges
- id: extract
  component: claim_extract
  inputs:
    bundle: segment.bundle
- id: verify
  component: claim_verify
  params:
    lang: $params.lang
  inputs:
    case: ingest.case
    claims: extract.claims
- id: consistency
  component: consistency_check
  params:
    lang: $params.lang
  inputs:
    claims: verify.verified
    charges: classify.charges
- id: map
  component: argument_map
  params:
    lang: $params.lang
  inputs:
    claims: verify.verified
    charges: classify.charges
    anomalies: consistency.anomalies
- id: law
  component: authority_select
  params:
    corpus_path: $params.corpus_path
    lang: $params.lang
  inputs:
    points: map.points
- id: dossier
  component: dossier_build
  params:
    lang: $params.lang
  inputs:
    case: ingest.case
    charges: classify.charges
    claims: verify.verified
    anomalies: consistency.anomalies
    points: map.points
    authorities: law.authorities
outputs:
  dossier: dossier.dossier
  rejected: verify.rejected
---
# Analyse a criminal case

## When to use
Start of work on a petition: it produces the dossier the rebuttal writer argues from.

## Procedure
1. `process_ingest` and `crime_classify`: the record and the elements to prove.
2. `evidence_segment`, `claim_extract`, `claim_verify`: claims that provably sit at their locators.
3. `consistency_check` and `argument_map`: anomalies, strong and weak points, refutation targets.
4. `authority_select` and `dossier_build`: authorities per point and the final dossier.
