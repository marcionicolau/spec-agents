---
name: dossier_build
version: 1.0.0
domain: legal
category: packaging
description: Bundle charges, claims, anomalies, points, authorities and page sizes into one dossier for writer and checker.
runtime: code
params: {}
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
- `rules` repeats the three writing rules so they travel with the data.
