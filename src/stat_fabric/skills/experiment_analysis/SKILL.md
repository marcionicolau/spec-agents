---
name: experiment_analysis
kind: pipeline
version: 1.0.0
domain: statistics
category: inferential
description: Summary, ANOVA of the response across treatment factors and a linear model with covariates.
params:
  response: {description: numeric outcome column, required: true, example: yield_t_ha}
  factors:
    description: 1-2 categorical treatment columns
    required: true
    example: [treatment]
  predictors:
    description: covariates and/or factors for the linear model
    required: true
    example: [nitrogen, treatment]
inputs:
  data: {type: dataframe, description: experiment dataset}
steps:
- {id: summary, component: summary}
- id: anova
  component: anova
  params: {response: $params.response, factors: $params.factors}
- id: model
  component: linear_model
  params: {response: $params.response, predictors: $params.predictors}
outputs: {anova: anova.result, model: model.result}
---
# Designed-experiment analysis

## When to use
A field or lab experiment with treatment factors and a numeric response. Examples: nitrogen doses,
cultivars, fungicide programmes.

## Procedure
1. `summary`: check balance and missing values.
2. `anova` on `factors`: are there treatment differences, and which pairs differ?
3. `linear_model` with `predictors`: estimate the effect sizes after adjusting for covariates such as rainfall.

## Interpreting
The ANOVA answers "is there a difference". The linear model answers "how large, adjusted for covariates".
Report both and check that they agree.
