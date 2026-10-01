---
name: anova
version: 1.0.0
domain: statistics
category: inferential
description: One- or two-way ANOVA with partial eta-squared, Levene and Shapiro checks and Tukey HSD post-hoc (one-way).
runtime: code
params:
  response: {description: numeric outcome column, example: yield}
  factors:
    description: 1 or 2 categorical grouping columns
    example: [treatment]
  interaction: {description: include factor interaction in two-way ANOVA, example: true}
  anova_type: {description: 'sum of squares type: 1, 2 or 3', example: 2}
  posthoc: {description: run Tukey HSD (one-way only), example: true}
  alpha: {description: significance level, example: 0.05}
inputs:
  data:
    type: dataframe
    description: the dataset
    constraints:
      min_rows: 6
      roles:
      - {role: response, param: response, dtype: numeric}
      - role: factors
        param: factors
        dtype: categorical
        multiple: true
        min_count: 1
        max_count: 2
        max_levels: 30
---
# Analysis of variance

## When to use
Compare the mean of a numeric outcome across groups defined by one or two categorical factors,
e.g. yield across nitrogen treatments or treatment × cultivar in a factorial trial.

## When not to use
The grouping variable is continuous (use `linear_model`), or groups have fewer than 2 observations each.

## Interpreting
- Each row of `table` is a source of variation. Report F, p and `eta_sq_partial` (≈0.01 small,
  0.06 medium, 0.14 large).
- In two-way designs, interpret the interaction first. A significant interaction means main effects
  depend on the other factor.
- `tukey` lists which pairs of groups differ (one-way only). Mention the direction using `group_means`.
- Small `levene_p` means unequal variances (suggest Welch ANOVA). Small `shapiro_resid_p` means
  non-normal residuals (suggest Kruskal-Wallis).

## Common mistakes
- Passing numeric columns in `factors`.
- Using more than two factors: only 1 or 2 are supported.
- Using `anova_type` = 1 with unbalanced designs: the results depend on factor order. Prefer 2, or 3 with interactions.
