"""Statistics domain: component results and data validation errors."""

import numpy as np
import pandas as pd
import pytest

from agent_fabric.errors import ComponentExecutionError, DataValidationError, ErrorCategory, ParamsValidationError
from agent_fabric.tabular import ColumnKind, profile_dataframe

from .conftest import run_component


def details(exc):
    return {(".".join(map(str, d.loc)), d.type): d for d in exc.details}


def test_profile_detects_kinds(df):
    p = profile_dataframe(df)
    assert p.column("date").kind == ColumnKind.DATETIME
    assert p.column("treatment").kind == ColumnKind.CATEGORICAL
    assert p.column("yield_t_ha").kind == ColumnKind.NUMERIC


def test_summary(registry, df):
    r, _ = run_component(registry, "summary", data=df)
    assert r.numeric["yield_t_ha"].missing == 2 and set(r.categorical) == {"treatment", "cultivar"}


def test_linear_model(registry, df):
    r, _ = run_component(
        registry,
        "linear_model",
        {"response": "yield_t_ha", "predictors": ["nitrogen", "rainfall", "treatment"]},
        data=df,
    )
    coefs = {c.term: c for c in r.coefficients}
    assert coefs["nitrogen"].significant and 0.01 < coefs["nitrogen"].estimate < 0.03
    assert "treatment[N60]" in coefs and r.r_squared > 0.5 and r.n_used == 118


def test_anova_one_and_two_way(registry, df):
    r, _ = run_component(registry, "anova", {"response": "yield_t_ha", "factors": ["treatment"]}, data=df)
    assert next(x for x in r.table if x.source == "treatment").p_value < 1e-6 and len(r.tukey) == 3
    r2, _ = run_component(
        registry, "anova", {"response": "yield_t_ha", "factors": ["treatment", "cultivar"], "anova_type": 3}, data=df
    )
    assert any(x.source == "treatment:cultivar" for x in r2.table)


def test_time_series(registry, df):
    r, _ = run_component(
        registry, "time_series", {"time_col": "date", "value_col": "yield_t_ha", "horizon": 6}, data=df
    )
    assert r.freq == "MS" and r.n_periods == 120 and len(r.forecast) == 6
    assert all(f.lower <= f.mean <= f.upper for f in r.forecast)


def test_pca_emits_scores_and_loadings(registry, df):
    r, store = run_component(
        registry, "pca", {"features": ["nitrogen", "phosphorus", "potassium", "ph"], "variance_threshold": 0.7}, data=df
    )
    assert r.cumulative_variance[-1] >= 0.7 and "nitrogen" in r.components["PC1"].top_features[:2]
    assert store.get("t.scores").shape == (120, r.n_components)
    assert store.get("t.loadings").shape == (4, r.n_components)


def test_clustering_on_matrix_and_features(registry, df):
    r, store = run_component(registry, "clustering", {"features": ["nitrogen", "potassium"], "k": 3}, data=df)
    assert r.k == 3 and 20 < np.mean([c["nitrogen"] for c in r.centers.values()]) < 60
    assert len(store.get("t.labels")) == 120
    m = pd.DataFrame({"PC1": np.r_[np.zeros(20), np.ones(20) * 5], "PC2": np.r_[np.zeros(20), np.ones(20) * 5]})
    m += np.random.default_rng(0).normal(0, 0.1, m.shape)
    r2, _ = run_component(registry, "clustering", {}, matrix=m)
    assert r2.k == 2 and r2.space == "matrix" and r2.silhouette > 0.9


# ------------------------------------------------------------------ validation


def test_missing_column_has_suggestion(registry, df):
    with pytest.raises(DataValidationError) as ei:
        run_component(registry, "linear_model", {"response": "yield", "predictors": ["nitrogen"]}, data=df)
    assert "yield_t_ha" in details(ei.value)[("params.response", "column_not_found")].hint
    assert ei.value.report.recoverable and ei.value.report.category == ErrorCategory.DATA


def test_wrong_dtype_lists_valid_columns(registry, df):
    with pytest.raises(DataValidationError) as ei:
        run_component(registry, "anova", {"response": "yield_t_ha", "factors": ["nitrogen"]}, data=df)
    assert "treatment" in details(ei.value)[("params.factors", "wrong_dtype")].hint


def test_wrong_artifact_type(registry, note):
    with pytest.raises(DataValidationError) as ei:
        run_component(registry, "summary", data=note)
    assert ("inputs.data", "wrong_artifact_type") in details(ei.value)


def test_extra_param_and_literal_errors(registry, df):
    with pytest.raises(ParamsValidationError) as ei:
        run_component(registry, "pca", {"features": ["nitrogen", "ph"], "n_pcs": 2}, data=df)
    assert "remove" in details(ei.value)[("params.n_pcs", "extra_forbidden")].hint
    with pytest.raises(ParamsValidationError) as ei:
        run_component(
            registry,
            "linear_model",
            {"response": "yield_t_ha", "predictors": ["nitrogen"], "robust_se": "HC1"},
            data=df,
        )
    assert "HC3" in ei.value.details[0].hint


def test_formula_injection_is_impossible(registry, df):
    with pytest.raises(ParamsValidationError):
        run_component(
            registry,
            "linear_model",
            {"response": 'yield_t_ha") + __import__("os").system("id") + Q("x', "predictors": ["nitrogen"]},
            data=df,
        )


def test_constant_column_and_too_few_rows(registry):
    d = pd.DataFrame({"a": range(20), "b": [1.0] * 20, "c": range(20, 40)})
    with pytest.raises(DataValidationError) as ei:
        run_component(registry, "pca", {"features": ["a", "b", "c"]}, data=d)
    assert ("params.features", "constant_column") in details(ei.value)
    small = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 1.0, 2.0]})
    with pytest.raises(DataValidationError) as ei:
        run_component(registry, "clustering", {"features": ["a", "b"]}, data=small)
    assert ("inputs.data", "too_few_rows") in details(ei.value)


def test_anova_small_group_and_log_response(registry, df):
    d = df.copy()
    d.loc[0, "treatment"] = "rare"
    with pytest.raises(DataValidationError) as ei:
        run_component(registry, "anova", {"response": "yield_t_ha", "factors": ["treatment"]}, data=d)
    assert "merge rare levels" in details(ei.value)[("params.factors", "small_group")].hint
    with pytest.raises(DataValidationError) as ei:
        run_component(
            registry,
            "linear_model",
            {"response": "y", "predictors": ["nitrogen"], "log_response": True},
            data=df.assign(y=df["yield_t_ha"] - 3),
        )
    assert ("params.log_response", "non_positive_response") in details(ei.value)


def test_numeric_failure_wrapped(registry, df, monkeypatch):
    comp = registry.get("summary")
    monkeypatch.setattr(
        comp, "compute", lambda *a, **k: (_ for _ in ()).throw(ValueError("could not convert string to float: 'x'"))
    )
    with pytest.raises(ComponentExecutionError) as ei:
        run_component(registry, "summary", data=df)
    assert ei.value.report.recoverable and "non-numeric" in ei.value.report.details[0].hint


def test_collinearity_warning(registry, df):
    r, _ = run_component(
        registry,
        "linear_model",
        {"response": "yield_t_ha", "predictors": ["nitrogen", "n2"]},
        data=df.assign(n2=df["nitrogen"] * 2),
    )
    assert any("multicollinearity" in w for w in r.warnings)
