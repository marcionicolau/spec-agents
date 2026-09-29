---
name: pca
version: 1.0.0
domain: statistics
category: multivariate
description: Standardised PCA with variance-based component selection, correlation-scale loadings, Kaiser criterion,
  Bartlett sphericity and KMO adequacy.
params:
  features:
    description: numeric columns to reduce (>= 2)
    example: [n, p, k, ph]
  n_components: {description: fixed number of components; null = use variance_threshold, example: null}
  variance_threshold: {description: cumulative explained variance to retain when n_components is null, example: 0.8}
  standardize: {description: z-score features first (recommended when units differ), example: true}
  top_loadings: {description: how many dominant features to list per component, example: 3}
inputs:
  data:
    type: dataframe
    description: the dataset
    constraints:
      min_rows: 5
      roles:
      - role: features
        param: features
        dtype: numeric
        multiple: true
        min_count: 2
outputs:
  scores: {type: dataframe, description: observation scores on the retained PCs (PC1..PCk)}
  loadings: {type: dataframe, description: feature x PC loadings}
---
# Principal component analysis

## When to use
Several correlated numeric variables need summarising (soil N, P, K, pH, organic matter),
or dimensions must be reduced before `clustering`.

## When not to use
Fewer than 3 numeric variables, or variables that are nearly uncorrelated. A large `bartlett_p`
then confirms that PCA adds little.

## Interpreting
- `cumulative_variance` says how much information the kept components retain.
- Name each component by its `top_features` and the signs of their loadings
  (e.g. "PC1: fertility gradient, N and P load positively").
- `kaiser_n` counts eigenvalues above 1, a rule-of-thumb for how many components matter.
- A `kmo` below 0.5 or a `bartlett_p` above 0.05 means the PCA structure is weak. Report it as a caveat.
- See [worked examples](references/interpretation_examples.md) for wording.

## Common mistakes
- Including identifiers or the response variable in `features`.
- Setting `standardize` to false with variables on different units.
- Asking for more `n_components` than `features`.
