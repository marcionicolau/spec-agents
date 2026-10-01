---
name: full_study
kind: pipeline
version: 1.0.0
domain: statistics
category: pipeline
description: Runs experiment_analysis and exploratory_analysis as nested pipelines on the same dataset.
params:
  response: {description: numeric outcome column, required: true}
  factors: {description: categorical treatment columns, required: true}
  predictors: {description: linear model predictors, required: true}
  features: {description: numeric columns for the multivariate profile, required: true}
inputs:
  data: {type: dataframe, description: study dataset}
steps:
- id: experiment
  component: experiment_analysis
  params: {response: $params.response, factors: $params.factors, predictors: $params.predictors}
- id: profile
  component: exploratory_analysis
  params: {features: $params.features}
outputs: {labels: profile.labels}
---
# Full study

## When to use
A complete report of a designed experiment plus a multivariate profile of the experimental units.

## Procedure
Runs `experiment_analysis` and `exploratory_analysis` as nested pipelines on the same dataset. Each
keeps its own steps and warnings. The cluster `labels` of the profile are exposed.
