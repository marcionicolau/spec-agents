---
name: exploratory_analysis
kind: pipeline
version: 1.0.0
domain: statistics
category: multivariate
description: Descriptive summary, PCA on numeric features and k-means clustering on the PCA scores.
params:
  features:
    description: numeric columns for the PCA (>= 2)
    required: true
    example: [nitrogen, phosphorus, ph]
  variance_threshold: {description: cumulative variance retained by the PCA, default: 0.8}
  k: {description: fixed number of clusters; null = choose by silhouette, default: null}
inputs:
  data: {type: dataframe, description: dataset with numeric features}
steps:
- {id: summary, component: summary}
- id: pca
  component: pca
  params: {features: $params.features, variance_threshold: $params.variance_threshold}
- id: clusters
  component: clustering
  params: {k: $params.k}
  inputs: {matrix: pca.scores}
outputs: {scores: pca.scores, labels: clusters.labels}
---
# Exploratory multivariate analysis

## When to use
Profile observations across many numeric variables. For example: "are there types of plots by soil
fertility?"

## Procedure
1. `summary`: check missing values and correlations first. PCA on mostly-missing columns is meaningless.
2. `pca` on `features`: keep enough components for `variance_threshold`.
3. `clustering` on `pca.scores`: fewer, uncorrelated dimensions make k-means distances meaningful.

The exposed outputs are `scores` (the PCA scores) and `labels` (cluster labels, one per observation).

## Interpreting
Name the components first, then describe the clusters in terms of those components.
