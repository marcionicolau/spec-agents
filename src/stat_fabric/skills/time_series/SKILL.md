---
name: time_series
version: 1.0.0
domain: statistics
category: temporal
description: Regularises a series to a fixed frequency, tests stationarity (ADF), measures trend/seasonal strength
  (STL) and forecasts with ARIMA.
params:
  time_col: {description: date/time column, example: date}
  value_col: {description: numeric value column, example: sales}
  freq: {description: 'pandas offset alias such as ''D'', ''W'', ''MS''; null = infer', example: MS}
  aggregate: {description: 'how to aggregate duplicates within a period: mean, sum or last', example: mean}
  period: {description: seasonal period in observations; null = derive from freq, example: 12}
  horizon: {description: number of periods to forecast (0 = none), example: 12}
  order:
    description: ARIMA (p, d, q) order
    example: [1, 1, 1]
  alpha: {description: forecast interval significance level, example: 0.05}
inputs:
  data:
    type: dataframe
    description: the dataset
    constraints:
      min_rows: 12
      roles:
      - {role: time, param: time_col, dtype: datetime, max_missing_ratio: 0.05}
      - {role: value, param: value_col, dtype: numeric}
---
# Time series analysis

## When to use
There is a date column and the question is about trends, seasonality or a forecast,
e.g. monthly yield, rainfall or prices.

## When not to use
Fewer than 12 periods, or observations that are not ordered in time.

## Interpreting
- `stationary` (from `adf_p_value`) says whether the level wanders. A non-stationary series needs
  differencing: the d in `order`.
- `trend_strength` and `seasonal_strength` range from 0 to 1. Above ~0.6 is strong.
- Report the last point of the `forecast` together with its interval. Wide intervals mean low predictability.
- Plain ARIMA ignores seasonality. If `seasonal_strength` is high, say that the forecast is conservative.

## Common mistakes
- Passing a numeric column as `time_col`.
- Choosing `period` longer than half the series.
- Leaving `freq` unset when dates are irregular. Set `freq` to 'MS' for monthly data or 'W' for weekly data.
