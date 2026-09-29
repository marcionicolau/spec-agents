---
name: clustering
version: 2.0.0
domain: statistics
category: unsupervised
description: K-means on standardised features or on PCA scores, with k chosen by silhouette when not fixed.
params:
  features:
    description: numeric columns of 'data' (>= 2); omit when 'matrix' is bound
    example: [n, p, k]
  k: {description: fixed number of clusters; null = choose by silhouette, example: null}
  k_min: {description: smallest k to try, example: 2}
  k_max: {description: largest k to try, example: 8}
  standardize: {description: z-score features first, example: true}
  random_state: {description: seed for reproducibility, example: 42}
inputs:
  data:
    type: dataframe
    description: the dataset
    constraints:
      min_rows: 10
      roles:
      - role: features
        param: features
        dtype: numeric
        multiple: true
        optional: true
        min_count: 2
    required: false
  matrix: {type: dataframe, required: false, description: 'numeric matrix to cluster instead of features, e.g. ''<pca_step>.scores'''}
outputs:
  labels: {type: series, description: cluster label per observation}
---
# K-means clustering

## When to use
Find natural groups of observations (plots, farms, seasons) across several numeric variables.
To cluster on PCA scores, bind the `matrix` input to `<pca_step>.scores` and omit `features`.

## When not to use
The groups are already known (use `anova`), or there are fewer than about 10 observations per expected cluster.

## Interpreting
- `silhouette` measures cluster separation. Above 0.5 is clear, 0.25–0.5 is moderate, and below 0.25 means
  the clusters are probably arbitrary.
- `silhouette_by_k` shows whether another k was nearly as good. Mention it when the scores are close.
- Describe each cluster by its `centers` (in original units when clustering `features`), and give `sizes`.
- Very small clusters are often outliers, not real groups.

## Common mistakes
- Giving both `features` and a bound `matrix`.
- Setting `k_max` larger than half the number of rows.
- Setting `standardize` to false with variables on different scales.
