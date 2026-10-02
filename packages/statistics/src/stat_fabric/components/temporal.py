from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.stattools import adfuller

from agent_fabric.errors import ErrorDetail
from agent_fabric.registry import component
from agent_fabric.tabular import coerce_datetime

from .base import ComponentParams, Num, StepContext, TableComponent, TableResult


class TimeSeriesParams(ComponentParams):
    time_col: str
    value_col: str
    freq: str | None = Field(None, description="pandas offset alias, e.g. 'D', 'W', 'MS'; None = infer")
    aggregate: Literal["mean", "sum", "last"] = "mean"
    period: int | None = Field(None, ge=2, le=366, description="seasonal period in observations")
    horizon: int = Field(12, ge=0, le=365)
    order: tuple[int, int, int] = (1, 1, 1)
    alpha: float = Field(0.05, gt=0, lt=0.5)


class ForecastPoint(BaseModel):
    time: str
    mean: Num
    lower: Num
    upper: Num


class TimeSeriesResult(TableResult):
    start: str
    end: str
    freq: str
    n_periods: int
    adf_statistic: Num
    adf_p_value: Num
    stationary: bool
    trend_strength: Num = None
    seasonal_strength: Num = None
    arima_order: tuple[int, int, int]
    arima_aic: Num
    forecast: list[ForecastPoint]


_PERIOD_BY_FREQ = {"D": 7, "B": 5, "W": 52, "M": 12, "MS": 12, "ME": 12, "Q": 4, "QS": 4, "QE": 4, "h": 24, "H": 24}


@component("time_series")
class TimeSeries(TableComponent[TimeSeriesParams, TimeSeriesResult]):
    Params = TimeSeriesParams
    Result = TimeSeriesResult

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        head = (
            f"{r['n_periods']} periods ({r['freq']}); series is "
            f"{'stationary' if r['stationary'] else 'non-stationary'} (ADF p={r['adf_p_value']:.3g})."
        )
        f = []
        if r.get("seasonal_strength") is not None:
            f.append(f"trend strength {r['trend_strength']:.2f}, seasonal strength {r['seasonal_strength']:.2f}")
        if r["forecast"]:
            last = r["forecast"][-1]
            f.append(f"forecast for {last['time']}: {last['mean']:.4g} [{last['lower']:.4g}, {last['upper']:.4g}]")
        return head, f

    def _series(self, df: pd.DataFrame, p: TimeSeriesParams) -> tuple[pd.Series, str]:
        d = df[[p.time_col, p.value_col]].copy()
        d[p.time_col] = coerce_datetime(d[p.time_col])
        d = d.dropna().sort_values(p.time_col)
        s = d.groupby(p.time_col)[p.value_col].agg(p.aggregate)
        freq = p.freq or (pd.infer_freq(s.index) if len(s) >= 3 else None)
        if freq is None:
            deltas = s.index.to_series().diff().dropna()
            days = deltas.dt.days.median() if len(deltas) else 1
            freq = "D" if days <= 1 else "W" if days <= 8 else "MS" if days <= 31 else "QS" if days <= 92 else "YS"
        s = s.resample(freq).agg(p.aggregate)
        return s.interpolate(limit_direction="both"), freq

    def extra_data_checks(self, df: pd.DataFrame, params: TimeSeriesParams) -> list[ErrorDetail]:
        """Check that the series can be regularised at the frequency and is long enough.

        Errors are ``bad_frequency`` (unusable ``freq``), ``too_few_periods`` and ``period_too_long`` (a seasonal period needs at least twice as many
        periods).
        """
        try:
            s, freq = self._series(df, params)
        except (ValueError, TypeError) as exc:
            return [
                ErrorDetail(
                    loc=("params", "freq"),
                    type="bad_frequency",
                    msg=str(exc)[:200],
                    hint="use a pandas offset alias such as 'D', 'W', 'MS' or leave freq null",
                )
            ]
        errors = []
        if len(s) < self.min_rows:
            errors.append(
                ErrorDetail(
                    loc=("params", "freq"),
                    type="too_few_periods",
                    msg=f"only {len(s)} periods at frequency '{freq}'",
                    hint="use a finer freq or more data",
                )
            )
        if params.period and len(s) < 2 * params.period:
            errors.append(
                ErrorDetail(
                    loc=("params", "period"),
                    type="period_too_long",
                    msg=f"seasonal period {params.period} needs >= {2 * params.period} periods, have {len(s)}",
                    hint="lower period or set it to null",
                )
            )
        return errors

    def compute_table(
        self, df: pd.DataFrame, params: TimeSeriesParams, ctx: StepContext, inputs: dict
    ) -> TimeSeriesResult:
        """Regularise the series, test stationarity and fit an ARIMA model with an optional forecast.

        Reports the Augmented Dickey-Fuller test, trend and seasonal strength from an STL decomposition (when the series spans at least two
        periods), the ARIMA fit and ``horizon`` forecast points with confidence intervals. Warns about non-stationarity with ``d=0``, strong
        seasonality that plain ARIMA ignores, and series too short for decomposition.
        """
        s, freq = self._series(df, params)
        warns = []
        adf_stat, adf_p = adfuller(s.values, autolag="AIC")[:2]
        period = params.period or _PERIOD_BY_FREQ.get(str(freq).lstrip("0123456789"))
        trend_str = seas_str = None
        if period and len(s) >= 2 * period:
            stl = STL(s, period=period, robust=True).fit()
            resid_var = np.var(stl.resid)
            trend_str = max(0.0, 1 - resid_var / np.var(stl.trend + stl.resid))
            seas_str = max(0.0, 1 - resid_var / np.var(stl.seasonal + stl.resid))
        else:
            warns.append("series too short for seasonal decomposition; seasonality not assessed")
        fit = ARIMA(s, order=params.order).fit()
        forecast = []
        if params.horizon:
            fc = fit.get_forecast(params.horizon)
            ci = fc.conf_int(alpha=params.alpha)
            forecast = [
                ForecastPoint(
                    time=str(idx.date() if hasattr(idx, "date") else idx),
                    mean=m,
                    lower=ci.iloc[i, 0],
                    upper=ci.iloc[i, 1],
                )
                for i, (idx, m) in enumerate(fc.predicted_mean.items())
            ]
        if adf_p >= 0.05 and params.order[1] == 0:
            warns.append(f"series looks non-stationary (ADF p={adf_p:.3g}) but order has d=0")
        if seas_str is not None and seas_str > 0.6:
            warns.append(f"strong seasonality (Fs={seas_str:.2f}); plain ARIMA ignores it, consider SARIMA/ETS")
        return TimeSeriesResult(
            n_used=len(s),
            start=str(s.index.min()),
            end=str(s.index.max()),
            freq=str(freq),
            n_periods=len(s),
            adf_statistic=adf_stat,
            adf_p_value=adf_p,
            stationary=bool(adf_p < 0.05),
            trend_strength=trend_str,
            seasonal_strength=seas_str,
            arima_order=params.order,
            arima_aic=fit.aic,
            forecast=forecast,
            warnings=warns,
        )


__all__ = [
    "ForecastPoint",
    "TimeSeries",
    "TimeSeriesParams",
    "TimeSeriesResult",
]
