"""Descriptive statistics: column-wise numeric/categorical summaries (``summary`` component)."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field
from scipy import stats

from agent_fabric.registry import component
from agent_fabric.tabular import ColumnKind, infer_kind

from .base import ComponentParams, Num, StepContext, TableComponent, TableResult


class SummaryParams(ComponentParams):
    columns: list[str] | None = Field(None, description="columns to describe; None = all")
    include_normality: bool = True
    max_categories: int = Field(10, ge=1, le=50)


class NumericSummary(BaseModel):
    count: int
    missing: int
    mean: Num
    std: Num
    min: Num
    q1: Num
    median: Num
    q3: Num
    max: Num
    skewness: Num
    kurtosis: Num
    shapiro_p: Num = None


class CategoricalSummary(BaseModel):
    count: int
    missing: int
    n_levels: int
    top_levels: dict[str, int]


class SummaryResult(TableResult):
    n_rows: int
    numeric: dict[str, NumericSummary]
    categorical: dict[str, CategoricalSummary]
    correlations: dict[str, dict[str, Num]] = Field(default_factory=dict)


@component("summary")
class Summary(TableComponent[SummaryParams, SummaryResult]):
    Params = SummaryParams
    Result = SummaryResult

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        head = f"{r['n_rows']} rows: {len(r['numeric'])} numeric and {len(r['categorical'])} categorical variables described."
        return head, [
            f"{k}: mean {v['mean']:.4g}, sd {v['std']:.4g}"
            for k, v in list(r["numeric"].items())[:5]
            if v["mean"] is not None and v["std"] is not None
        ]

    def compute_table(
        self, df: pd.DataFrame | None, params: SummaryParams, ctx: StepContext, inputs: dict
    ) -> SummaryResult:
        """Describe the selected columns.

        Numeric columns get count, missing values, mean, standard deviation, quartiles, skewness, kurtosis and, optionally, a Shapiro-Wilk
        normality test (only for 3 to 5000 values). Categorical and boolean columns get the number of levels and the top levels. With two or
        more numeric columns the Pearson correlation matrix is added. Warns about non-normal columns and columns with over 20% missing values.
        """
        assert df is not None
        cols = params.columns or list(df.columns)
        numeric, categorical, warns = {}, {}, []
        for c in cols:
            s = df[c]
            kind = infer_kind(s)
            if kind == ColumnKind.NUMERIC:
                x = s.dropna().astype(float)
                shapiro_p = None
                if params.include_normality and 3 <= len(x) <= 5000 and x.nunique() > 1:
                    shapiro_p = float(stats.shapiro(x).pvalue)
                    if shapiro_p < 0.05:
                        warns.append(f"'{c}' departs from normality (Shapiro p={shapiro_p:.3g})")
                numeric[c] = NumericSummary(
                    count=len(x),
                    missing=int(s.isna().sum()),
                    mean=x.mean(),
                    std=x.std(),
                    min=x.min(),
                    q1=x.quantile(0.25),
                    median=x.median(),
                    q3=x.quantile(0.75),
                    max=x.max(),
                    skewness=x.skew() if len(x) > 2 else None,
                    kurtosis=x.kurt() if len(x) > 3 else None,
                    shapiro_p=shapiro_p,
                )
            elif kind in (ColumnKind.CATEGORICAL, ColumnKind.BOOLEAN):
                vc = s.astype(str).where(s.notna()).value_counts()
                categorical[c] = CategoricalSummary(
                    count=int(s.notna().sum()),
                    missing=int(s.isna().sum()),
                    n_levels=int(vc.size),
                    top_levels={str(k): int(v) for k, v in vc.head(params.max_categories).items()},
                )
            if s.isna().mean() > 0.2:
                warns.append(f"'{c}' has {s.isna().mean():.0%} missing values")
        corr = {}
        if len(numeric) >= 2:
            m = df[list(numeric)].corr(method="pearson")
            corr = {a: {b: m.loc[a, b] for b in m.columns if b != a} for a in m.index}
            strong = {tuple(sorted((a, b))) for a in m.index for b in m.columns if a != b and abs(m.loc[a, b]) >= 0.9}
            warns += [f"'{a}' and '{b}' are highly correlated (|r|>=0.9)" for a, b in sorted(strong)]
        return SummaryResult(
            n_rows=len(df), n_used=len(df), numeric=numeric, categorical=categorical, correlations=corr, warnings=warns
        )


__all__ = [
    "CategoricalSummary",
    "NumericSummary",
    "Summary",
    "SummaryParams",
    "SummaryResult",
]
