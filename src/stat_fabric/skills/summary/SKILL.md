---
name: summary
version: 1.0.0
domain: statistics
category: descriptive
description: Univariate statistics for numeric and categorical columns, normality screening and Pearson correlations.
params:
  columns:
    description: columns to describe; null = all columns
    example: [yield, rainfall]
  include_normality: {description: run Shapiro-Wilk on numeric columns (n <= 5000), example: true}
  max_categories: {description: how many top levels to list per categorical column, example: 10}
inputs:
  data:
    type: dataframe
    description: the dataset
    constraints:
      min_rows: 1
      roles:
      - role: variables
        param: columns
        dtype: any
        multiple: true
        optional: true
        min_count: 0
        max_missing_ratio: 1.0
        allow_constant: true
      distinct_roles: false
---
# Descriptive summary

## When to use
Always as the first step: it shows distributions, missing values and pairwise correlations, which
decide what the later steps can safely assume.

## Interpreting
- Report `missing` counts first; more than ~20% missing in a variable weakens every later step.
- `skewness` beyond ±1 or a small `shapiro_p` means the variable is far from normal: prefer robust
  or transformed models and say so.
- Pairs in `correlations` with |r| ≥ 0.9 carry almost the same information; flag them before regression.
- For categorical variables, very unequal `top_levels` counts mean an unbalanced design.

## Common mistakes
- Listing every statistic. Pick the few that matter for the objective.
- Calling a variable "normal" because `shapiro_p` > 0.05 with very few rows (the test has low power).
