"""PCA and clustering. PCA publishes ``scores`` which clustering may consume."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA as SkPCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from agent_fabric.errors import ErrorDetail
from agent_fabric.registry import component

from .base import ComponentParams, Num, StepContext, TableComponent, TableResult

# =========================================================================== PCA


class PCAParams(ComponentParams):
    features: list[str] = Field(min_length=2)
    n_components: int | None = Field(None, ge=1, description="fixed number of PCs; None = use variance_threshold")
    variance_threshold: float = Field(0.8, gt=0, le=1)
    standardize: bool = True
    top_loadings: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def _check(self) -> PCAParams:
        if len(set(self.features)) != len(self.features):
            raise ValueError("features contain duplicates")
        if self.n_components is not None and self.n_components > len(self.features):
            raise ValueError(
                f"n_components ({self.n_components}) cannot exceed number of features ({len(self.features)})"
            )
        return self


class ComponentLoadings(BaseModel):
    explained_variance_ratio: Num
    eigenvalue: Num
    loadings: dict[str, Num]
    top_features: list[str]


class PCAResult(TableResult):
    n_components: int
    selection: Literal["fixed", "variance_threshold"]
    cumulative_variance: list[Num]
    kaiser_n: int = Field(description="number of eigenvalues > 1 (standardized data only)")
    bartlett_p: Num = Field(description="Bartlett sphericity test; p>0.05 means PCA is not meaningful")
    kmo: Num = Field(description="Kaiser-Meyer-Olkin sampling adequacy (0-1)")
    components: dict[str, ComponentLoadings]


def _kmo(corr: np.ndarray) -> float | None:
    try:
        inv = np.linalg.inv(corr)
    except np.linalg.LinAlgError:
        return None
    d = np.sqrt(np.outer(np.diag(inv), np.diag(inv)))
    partial = -inv / d
    np.fill_diagonal(partial, 0)
    r = corr.copy()
    np.fill_diagonal(r, 0)
    return float((r**2).sum() / ((r**2).sum() + (partial**2).sum()))


@component("pca")
class PCA(TableComponent[PCAParams, PCAResult]):
    Params = PCAParams
    Result = PCAResult

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        head = f"{r['n_components']} component(s) retain {r['cumulative_variance'][-1]:.1%} of the variance."
        return head, [
            f"{pc}: {v['explained_variance_ratio']:.1%}, driven by {', '.join(v['top_features'])}"
            for pc, v in r["components"].items()
        ]

    def extra_data_checks(self, df: pd.DataFrame, params: PCAParams) -> list[ErrorDetail]:
        n = len(df[params.features].dropna())
        if params.n_components and params.n_components > n:
            return [
                ErrorDetail(
                    loc=("params", "n_components"),
                    type="too_many_components",
                    msg=f"n_components={params.n_components} exceeds complete rows ({n})",
                )
            ]
        return []

    def compute_table(self, df: pd.DataFrame, params: PCAParams, ctx: StepContext, inputs: dict) -> PCAResult:
        d = df[params.features].dropna().astype(float)
        X = StandardScaler().fit_transform(d) if params.standardize else (d - d.mean()).values
        full = SkPCA().fit(X)
        cum = np.cumsum(full.explained_variance_ratio_)
        if params.n_components:
            k, selection = params.n_components, "fixed"
        else:
            k, selection = int(np.searchsorted(cum, params.variance_threshold - 1e-12) + 1), "variance_threshold"
        k = min(k, len(params.features))
        pca = SkPCA(n_components=k).fit(X)
        names = [f"PC{i + 1}" for i in range(k)]
        comps = {}
        for i, pc in enumerate(names):
            load = pca.components_[i] * np.sqrt(pca.explained_variance_[i])  # correlation-scale loadings
            ld = dict(zip(params.features, load, strict=True))
            top = sorted(ld, key=lambda f: abs(ld[f]), reverse=True)[: params.top_loadings]
            comps[pc] = ComponentLoadings(
                explained_variance_ratio=pca.explained_variance_ratio_[i],
                eigenvalue=pca.explained_variance_[i],
                loadings=ld,
                top_features=top,
            )
        corr = np.corrcoef(d.values, rowvar=False)
        n, p = d.shape
        det = np.linalg.det(corr)
        bartlett_p = None
        if det > 0:
            chi2 = -(n - 1 - (2 * p + 5) / 6) * np.log(det)
            bartlett_p = float(stats.chi2.sf(chi2, p * (p - 1) / 2))
        kmo = _kmo(corr)
        warns = []
        if bartlett_p is not None and bartlett_p > 0.05:
            warns.append(
                f"Bartlett test not significant (p={bartlett_p:.3g}): variables are weakly correlated, PCA adds little"
            )
        if kmo is not None and kmo < 0.5:
            warns.append(f"KMO={kmo:.2f} < 0.5: sampling adequacy is poor")
        if not params.standardize and d.std().max() > 10 * d.std().min():
            warns.append(
                "features on very different scales without standardization; PCs dominated by large-variance variables"
            )
        scores = pd.DataFrame(pca.transform(X), index=d.index, columns=names)
        ctx.emit("scores", scores)
        ctx.emit("loadings", pd.DataFrame(pca.components_.T, index=params.features, columns=names))
        kaiser = int((full.explained_variance_ > 1).sum()) if params.standardize else 0
        return PCAResult(
            n_used=n,
            n_components=k,
            selection=selection,
            cumulative_variance=list(cum[:k]),
            kaiser_n=kaiser,
            bartlett_p=bartlett_p,
            kmo=kmo,
            components=comps,
            warnings=warns,
        )


# =========================================================================== Clustering


class ClusteringParams(ComponentParams):
    features: list[str] | None = Field(None, description="numeric columns of 'data'; omit when 'matrix' is bound")
    k: int | None = Field(None, ge=2, le=20, description="fixed number of clusters; None = choose by silhouette")
    k_min: int = Field(2, ge=2)
    k_max: int = Field(8, le=20)
    standardize: bool = True
    random_state: int = 42

    @model_validator(mode="after")
    def _check(self) -> ClusteringParams:
        if self.features is not None and len(self.features) < 2:
            raise ValueError("features needs at least 2 columns")
        if self.k_min > self.k_max:
            raise ValueError(f"k_min ({self.k_min}) must be <= k_max ({self.k_max})")
        return self


class ClusteringResult(TableResult):
    k: int
    selection: Literal["fixed", "silhouette"]
    space: Literal["features", "matrix"]
    silhouette: Num
    silhouette_by_k: dict[str, Num] = Field(default_factory=dict)
    sizes: dict[str, int]
    centers: dict[str, dict[str, Num]]


@component("clustering")
class Clustering(TableComponent[ClusteringParams, ClusteringResult]):
    Params = ClusteringParams
    Result = ClusteringResult

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        head = f"{r['k']} clusters (silhouette {r['silhouette']:.2f}, space: {r['space']})."
        return head, [f"cluster {k}: {n} observations" for k, n in r["sizes"].items()]

    def extra_static(self, bound: dict, params: ClusteringParams) -> list[ErrorDetail]:
        has_matrix = "matrix" in bound
        if has_matrix and params.features:
            return [
                ErrorDetail(
                    loc=("params", "features"),
                    type="ambiguous_source",
                    msg="both 'features' and a bound 'matrix' input were given",
                    hint="drop 'features' to cluster the matrix, or unbind 'matrix'",
                )
            ]
        if not has_matrix and not params.features:
            return [
                ErrorDetail(
                    loc=("inputs", "matrix"),
                    type="no_source",
                    msg="nothing to cluster: set 'features' or bind 'matrix'",
                    hint="e.g. inputs: {matrix: '<pca_step_id>.scores'}",
                )
            ]
        if params.features and "data" not in bound:
            return [
                ErrorDetail(
                    loc=("inputs", "data"),
                    type="port_unbound",
                    msg="'features' needs the 'data' input",
                    hint="bind data to '$inputs.<dataframe>'",
                )
            ]
        return []

    def extra_checks(self, inputs: dict, params: ClusteringParams) -> list[ErrorDetail]:
        m = inputs.get("matrix")
        if m is not None and params.features is None:
            bad = [c for c in m.columns if not pd.api.types.is_numeric_dtype(m[c])]
            if bad:
                return [
                    ErrorDetail(loc=("inputs", "matrix"), type="wrong_dtype", msg=f"non-numeric matrix columns {bad}")
                ]
            n = len(m.dropna())
        elif params.features and inputs.get("data") is not None:
            n = len(inputs["data"][params.features].dropna())
        else:
            return []
        if n < self.min_rows:
            return [ErrorDetail(loc=("inputs",), type="too_few_rows", msg=f"{n} complete rows; need {self.min_rows}")]
        top = params.k or params.k_max
        if n < 2 * top:
            return [
                ErrorDetail(
                    loc=("params", "k" if params.k else "k_max"),
                    type="too_few_rows",
                    msg=f"{n} complete rows is too few for up to {top} clusters",
                    hint=f"use k <= {max(2, n // 2)}",
                )
            ]
        return []

    def compute_table(
        self, df: pd.DataFrame, params: ClusteringParams, ctx: StepContext, inputs: dict
    ) -> ClusteringResult:
        if params.features is None:
            data = inputs["matrix"].dropna().astype(float)
            X, space, scaler = data.values, "matrix", None
        else:
            data = df[params.features].dropna().astype(float)
            scaler = StandardScaler().fit(data) if params.standardize else None
            X, space = (scaler.transform(data) if scaler else data.values), "features"
        n = len(X)
        warns: list[str] = []
        sil_by_k: dict[str, float] = {}
        if params.k:
            k, selection = params.k, "fixed"
        else:
            upper = min(params.k_max, n - 1)
            best = None
            for kk in range(params.k_min, upper + 1):
                labels = KMeans(kk, n_init=10, random_state=params.random_state).fit_predict(X)
                sil_by_k[str(kk)] = float(silhouette_score(X, labels))
                if best is None or sil_by_k[str(kk)] > sil_by_k[str(best)]:
                    best = kk
            k, selection = int(best), "silhouette"
        km = KMeans(k, n_init=10, random_state=params.random_state).fit(X)
        sil = float(silhouette_score(X, km.labels_))
        centers_arr = km.cluster_centers_
        if scaler is not None:
            centers_arr = scaler.inverse_transform(centers_arr)  # report in original units
        cols = list(data.columns)
        centers = {str(i): dict(zip(cols, map(float, c), strict=True)) for i, c in enumerate(centers_arr)}
        sizes = {str(i): int((km.labels_ == i).sum()) for i in range(k)}
        if sil < 0.25:
            warns.append(f"weak cluster structure (silhouette={sil:.2f}); clusters may be arbitrary")
        if min(sizes.values()) < max(3, 0.05 * n):
            warns.append("at least one very small cluster (possible outliers)")
        if not params.standardize and space == "features":
            warns.append("unstandardized features: distances dominated by large-scale variables")
        ctx.emit("labels", pd.Series(km.labels_, index=data.index, name="cluster"))
        return ClusteringResult(
            n_used=n,
            k=k,
            selection=selection,
            space=space,
            silhouette=sil,
            silhouette_by_k=sil_by_k,
            sizes=sizes,
            centers=centers,
            warnings=warns,
        )


__all__ = [
    "Clustering",
    "ClusteringParams",
    "ClusteringResult",
    "ComponentLoadings",
    "PCAParams",
    "PCAResult",
]
