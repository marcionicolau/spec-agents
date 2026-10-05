"""Linear model (OLS) and ANOVA components.

Formulas are *built* from validated column names (``Q("...")`` quoting) and never
accepted as free text: a patsy formula can evaluate Python, so an LLM must not
be able to inject one.
"""

from __future__ import annotations

import re
from typing import Literal

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from pydantic import BaseModel, Field, field_validator, model_validator
from scipy import stats
from statsmodels.stats.anova import anova_lm
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, jarque_bera

from agent_fabric.errors import ErrorDetail
from agent_fabric.registry import component
from agent_fabric.tabular import ColumnKind, infer_kind

from .base import ComponentParams, Num, StepContext, TableComponent, TableResult


def _term(df: pd.DataFrame, col: str) -> str:
    q = f'Q("{col}")'
    return f"C({q})" if infer_kind(df[col]) != ColumnKind.NUMERIC else q


_C_TERM = re.compile(r'C\(Q\("([^"]+)"\)(?:, Sum)?\)')
_Q_TERM = re.compile(r'Q\("([^"]+)"\)')
_LEVEL = re.compile(r"\[[TS]\.([^\]]+)\]")


def pretty_term(term: str) -> str:
    """'C(Q("treatment"))[T.N60]' -> 'treatment[N60]', 'Q("nitrogen")' -> 'nitrogen'."""
    return _LEVEL.sub(r"[\1]", _Q_TERM.sub(r"\1", _C_TERM.sub(r"\1", term)))


def _no_quotes(v: str) -> str:
    if '"' in v or "\\" in v:
        raise ValueError("column names may not contain quotes or backslashes")
    return v


# =========================================================================== linear model


class LinearModelParams(ComponentParams):
    response: str
    predictors: list[str] = Field(min_length=1)
    interactions: list[tuple[str, str]] = Field(default_factory=list, description="pairs of predictors")
    log_response: bool = False
    robust_se: Literal["none", "HC3"] = "none"
    alpha: float = Field(0.05, gt=0, lt=0.5)

    @field_validator("response")
    @classmethod
    def _q(cls, v: str) -> str:
        return _no_quotes(v)

    @field_validator("predictors")
    @classmethod
    def _qs(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("predictors contain duplicates")
        return [_no_quotes(x) for x in v]

    @model_validator(mode="after")
    def _check(self) -> LinearModelParams:
        if self.response in self.predictors:
            raise ValueError("response cannot also be a predictor")
        bad = [p for pair in self.interactions for p in pair if p not in self.predictors]
        if bad:
            raise ValueError(f"interaction terms must use listed predictors, unknown: {sorted(set(bad))}")
        return self


class Coefficient(BaseModel):
    term: str
    estimate: Num
    std_error: Num
    statistic: Num
    p_value: Num
    ci_low: Num
    ci_high: Num
    significant: bool


class LinearModelResult(TableResult):
    formula: str
    coefficients: list[Coefficient]
    r_squared: Num
    adj_r_squared: Num
    f_statistic: Num
    f_p_value: Num
    aic: Num
    bic: Num
    breusch_pagan_p: Num
    jarque_bera_p: Num
    durbin_watson: Num
    vif: dict[str, Num]


@component("linear_model")
class LinearModel(TableComponent[LinearModelParams, LinearModelResult]):
    Params = LinearModelParams
    Result = LinearModelResult

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        sig = [x for x in r["coefficients"] if x["significant"] and x["term"] != "Intercept"]
        head = f"Model explains R² = {r['r_squared']:.3f} of the variance; {len(sig)} significant term(s)."
        return head, [f"{x['term']}: estimate {x['estimate']:.4g} (p={x['p_value']:.3g})" for x in sig[:5]]

    def extra_data_checks(self, df: pd.DataFrame, params: LinearModelParams) -> list[ErrorDetail]:
        """``log_response`` needs a strictly positive response, and the complete rows must exceed the number of model terms.

        Errors are ``non_positive_response`` and ``too_many_terms``.
        """
        d = df[[params.response, *params.predictors]].dropna()
        errors = []
        if params.log_response and (d[params.response] <= 0).any():
            errors.append(
                ErrorDetail(
                    loc=("params", "log_response"),
                    type="non_positive_response",
                    msg="log_response requires a strictly positive response",
                    hint="set log_response=false",
                )
            )
        n_terms = 1 + sum(
            1 if infer_kind(d[p]) == ColumnKind.NUMERIC else max(d[p].nunique() - 1, 1) for p in params.predictors
        )
        n_terms += len(params.interactions)
        if len(d) <= n_terms + 1:
            errors.append(
                ErrorDetail(
                    loc=("params", "predictors"),
                    type="too_many_terms",
                    msg=f"{len(d)} complete rows cannot support {n_terms} model terms",
                    hint="use fewer predictors or drop interactions",
                )
            )
        return errors

    def compute_table(
        self, df: pd.DataFrame | None, params: LinearModelParams, ctx: StepContext, inputs: dict
    ) -> LinearModelResult:
        """Fit an ordinary least squares model with a coefficient table and residual diagnostics.

        Terms are built from validated column names (categorical predictors become dummies; optional interactions and ``log_response``). Reports
        estimates, standard errors, test statistics, p-values and confidence intervals, the fit statistics, and diagnostics: Breusch-Pagan
        (heteroscedasticity), Jarque-Bera (residual normality), Durbin-Watson (autocorrelation) and variance inflation factors. Warns when a
        diagnostic fails (and suggests robust standard errors).
        """
        assert df is not None
        cols = [params.response, *params.predictors]
        d = df[cols].dropna().copy()
        if params.log_response:
            d[params.response] = np.log(d[params.response])
        y = f'Q("{params.response}")'
        terms = [_term(d, p) for p in params.predictors]
        terms += [f"{_term(d, a)}:{_term(d, b)}" for a, b in params.interactions]
        formula = f"{y} ~ {' + '.join(terms)}"
        model = smf.ols(formula, data=d, eval_env=0)
        fit = model.fit(cov_type=params.robust_se) if params.robust_se != "none" else model.fit()
        ci = fit.conf_int(alpha=params.alpha)
        coefs = [
            Coefficient(
                term=pretty_term(t),
                estimate=fit.params[t],
                std_error=fit.bse[t],
                statistic=fit.tvalues[t],
                p_value=fit.pvalues[t],
                ci_low=ci.loc[t, 0],
                ci_high=ci.loc[t, 1],
                significant=bool(fit.pvalues[t] < params.alpha),
            )
            for t in fit.params.index
        ]
        exog = model.exog
        bp_p = het_breuschpagan(fit.resid, exog)[1] if exog.shape[1] > 1 else None
        jb_p = jarque_bera(fit.resid)[1]
        dw = durbin_watson(fit.resid)
        vif = {}
        names = model.exog_names
        if exog.shape[1] > 2:
            for i, name in enumerate(names):
                if name != "Intercept":
                    vif[pretty_term(name)] = variance_inflation_factor(exog, i)
        warns = []
        if bp_p is not None and bp_p < 0.05 and params.robust_se == "none":
            warns.append(f"heteroscedasticity detected (Breusch-Pagan p={bp_p:.3g}); consider robust_se='HC3'")
        if jb_p < 0.05:
            warns.append(f"residuals are not normal (Jarque-Bera p={jb_p:.3g})")
        if not 1.5 <= dw <= 2.5:
            warns.append(f"possible residual autocorrelation (Durbin-Watson={dw:.2f})")
        warns += [
            f"high multicollinearity for {k} (VIF={v:.1f})" for k, v in vif.items() if not np.isnan(v) and v > 10
        ]  # inf = perfect collinearity (older numpy/statsmodels return inf, newer a huge value)
        return LinearModelResult(
            n_used=int(fit.nobs),
            formula=formula,
            coefficients=coefs,
            r_squared=fit.rsquared,
            adj_r_squared=fit.rsquared_adj,
            f_statistic=fit.fvalue,
            f_p_value=fit.f_pvalue,
            aic=fit.aic,
            bic=fit.bic,
            breusch_pagan_p=bp_p,
            jarque_bera_p=jb_p,
            durbin_watson=dw,
            vif=vif,
            warnings=warns,
        )


# =========================================================================== ANOVA


class AnovaParams(ComponentParams):
    response: str
    factors: list[str] = Field(min_length=1, max_length=2)
    interaction: bool = True
    anova_type: Literal[1, 2, 3] = 2
    posthoc: bool = True
    alpha: float = Field(0.05, gt=0, lt=0.5)

    @field_validator("response")
    @classmethod
    def _q(cls, v: str) -> str:
        return _no_quotes(v)

    @field_validator("factors")
    @classmethod
    def _qs(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("factors contain duplicates")
        return [_no_quotes(x) for x in v]


class AnovaRow(BaseModel):
    source: str
    sum_sq: Num
    df: Num
    f_value: Num
    p_value: Num
    eta_sq_partial: Num


class TukeyComparison(BaseModel):
    group_a: str
    group_b: str
    mean_diff: Num
    p_adj: Num
    ci_low: Num
    ci_high: Num
    reject: bool


class AnovaResult(TableResult):
    formula: str
    table: list[AnovaRow]
    group_means: dict[str, dict[str, Num]]
    levene_p: Num
    shapiro_resid_p: Num
    tukey: list[TukeyComparison] = Field(default_factory=list)


@component("anova")
class Anova(TableComponent[AnovaParams, AnovaResult]):
    Params = AnovaParams
    Result = AnovaResult

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        rows = [x for x in r["table"] if x["source"] != "Residual" and x["p_value"] is not None]
        head = "; ".join(f"{x['source']}: F={x['f_value']:.3g}, p={x['p_value']:.3g}" for x in rows)
        return head, [
            f"{x['group_a']} vs {x['group_b']}: diff {x['mean_diff']:.3g} (p adj={x['p_adj']:.3g})"
            for x in r.get("tukey", [])
            if x["reject"]
        ][:5]

    def extra_data_checks(self, df: pd.DataFrame, params: AnovaParams) -> list[ErrorDetail]:
        """Each factor needs at least 2 levels and every level at least 2 observations (after dropping missing values).

        Errors are ``single_level`` and ``small_group``.
        """
        d = df[[params.response, *params.factors]].dropna()
        errors = []
        for f in params.factors:
            counts = d[f].value_counts()
            if counts.size < 2:
                errors.append(
                    ErrorDetail(
                        loc=("params", "factors"),
                        type="single_level",
                        input=f,
                        msg=f"factor '{f}' has fewer than 2 levels",
                    )
                )
            elif counts.min() < 2:
                errors.append(
                    ErrorDetail(
                        loc=("params", "factors"),
                        type="small_group",
                        input=f,
                        msg=f"level '{counts.idxmin()}' of '{f}' has {counts.min()} observation(s); need >= 2",
                        hint="merge rare levels or filter them out",
                    )
                )
        return errors

    def compute_table(
        self, df: pd.DataFrame | None, params: AnovaParams, ctx: StepContext, inputs: dict
    ) -> AnovaResult:
        """One- or two-way ANOVA of the response across the factors.

        Fits an OLS model from validated column names (type 2 or 3 sums of squares, optional interaction for two factors), reports each source
        with partial eta-squared, Levene's test for equal variances, Shapiro-Wilk on the residuals, group means and, for a single factor with
        ``posthoc``, Tukey HSD pairwise comparisons.
        """
        assert df is not None
        d = df[[params.response, *params.factors]].dropna().copy()
        for f in params.factors:
            d[f] = d[f].astype(str)
        terms = [f'C(Q("{f}"))' for f in params.factors]
        sep = " * " if params.interaction and len(terms) == 2 else " + "
        contrast = ", Sum" if params.anova_type == 3 else ""
        if contrast:
            terms = [f'C(Q("{f}"){contrast})' for f in params.factors]
        formula = f'Q("{params.response}") ~ {sep.join(terms)}'
        fit = smf.ols(formula, data=d, eval_env=0).fit()
        tab = anova_lm(fit, typ=params.anova_type)
        ss_res = tab.loc["Residual", "sum_sq"]
        rows = []
        for src, r in tab.iterrows():
            eta = None if src == "Residual" else r["sum_sq"] / (r["sum_sq"] + ss_res)
            rows.append(
                AnovaRow(
                    source=pretty_term(str(src)),
                    sum_sq=r["sum_sq"],
                    df=r["df"],
                    f_value=r.get("F"),
                    p_value=r.get("PR(>F)"),
                    eta_sq_partial=eta,
                )
            )
        groups = [g[params.response].values for _, g in d.groupby(params.factors)]
        levene_p = stats.levene(*groups).pvalue if len(groups) > 1 else None
        shapiro_p = stats.shapiro(fit.resid).pvalue if 3 <= len(d) <= 5000 else None
        means = {f: {str(k): v for k, v in d.groupby(f)[params.response].mean().items()} for f in params.factors}
        tukey = []
        if params.posthoc and len(params.factors) == 1:
            res = pairwise_tukeyhsd(d[params.response], d[params.factors[0]], alpha=params.alpha)
            tbl = res.summary().data[1:]
            tukey = [
                TukeyComparison(
                    group_a=str(r[0]),
                    group_b=str(r[1]),
                    mean_diff=float(r[2]),
                    p_adj=float(r[3]),
                    ci_low=float(r[4]),
                    ci_high=float(r[5]),
                    reject=bool(r[6]),
                )
                for r in tbl
            ]
        warns = []
        if levene_p is not None and levene_p < 0.05:
            warns.append(f"unequal variances across groups (Levene p={levene_p:.3g}); consider Welch ANOVA")
        if shapiro_p is not None and shapiro_p < 0.05:
            warns.append(f"residuals are not normal (Shapiro p={shapiro_p:.3g}); consider Kruskal-Wallis")
        if params.posthoc and len(params.factors) > 1:
            warns.append("Tukey post-hoc is only computed for one-way ANOVA")
        sizes = d.groupby(params.factors).size()
        if sizes.max() > 1.5 * sizes.min() and params.anova_type == 1:
            warns.append("unbalanced design: Type I sums of squares depend on factor order")
        return AnovaResult(
            n_used=len(d),
            formula=formula,
            table=rows,
            group_means=means,
            levene_p=levene_p,
            shapiro_resid_p=shapiro_p,
            tukey=tukey,
            warnings=warns,
        )


__all__ = [
    "Anova",
    "AnovaParams",
    "AnovaResult",
    "AnovaRow",
    "Coefficient",
    "LinearModel",
    "LinearModelParams",
    "LinearModelResult",
    "TukeyComparison",
]
