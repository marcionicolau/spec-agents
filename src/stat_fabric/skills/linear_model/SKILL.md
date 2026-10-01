---
name: linear_model
version: 1.0.0
domain: statistics
category: inferential
description: Ordinary least squares with coefficient table, fit statistics and residual diagnostics (Breusch-Pagan,
  Jarque-Bera, Durbin-Watson, VIF).
runtime: code
params:
  response: {description: numeric outcome column, example: yield}
  predictors:
    description: explanatory columns (numeric or categorical)
    example: [rainfall, cultivar]
  interactions:
    description: pairs of predictors to interact
    example:
    - [rainfall, cultivar]
  log_response: {description: model log(response); response must be > 0, example: false}
  robust_se: {description: '''none'' or ''HC3'' heteroscedasticity-robust standard errors', example: none}
  alpha: {description: significance level, example: 0.05}
inputs:
  data:
    type: dataframe
    description: the dataset
    constraints:
      min_rows: 8
      roles:
      - {role: response, param: response, dtype: numeric}
      - role: predictors
        param: predictors
        dtype: any
        multiple: true
        min_count: 1
        max_count: 15
        max_levels: 30
---
# Linear regression (OLS)

## When to use
Quantify how a numeric outcome changes with one or more predictors (numeric or categorical),
e.g. yield as a function of nitrogen dose, rainfall and cultivar.

## When not to use
The outcome is categorical, a count with many zeros, or a proportion bounded at 0 and 1.
To compare group means only, use `anova`.

## Interpreting
- Lead with effect sizes: the `estimate` of each term in `coefficients`, with its confidence interval.
  Significance comes second.
- Categorical predictors appear as `treatment[N60]`: the difference from the reference level.
- `r_squared` is explained variance. Compare `adj_r_squared` when models have different numbers of terms.
- Diagnostics:
  - small `breusch_pagan_p` means heteroscedasticity; rerun with `robust_se` = HC3;
  - small `jarque_bera_p` means non-normal residuals;
  - `durbin_watson` far from 2 means autocorrelation (common in time-ordered plots);
  - `vif` above 10 means collinearity.
- Always repeat the component's warnings as caveats.

## Common mistakes
- Putting the response column in `predictors`.
- Using `interactions` with columns that are not in `predictors`.
- Setting `log_response` when the response has zeros or negatives.
- Too many `predictors` for the number of rows: keep at least 10 rows per term.
- Column names must match the dataset exactly (e.g. "yield_t_ha", not "yield").
