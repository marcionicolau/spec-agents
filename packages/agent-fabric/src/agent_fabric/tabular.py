"""Tabular artifact types: ``dataframe`` and ``series`` (pandas).

``DatasetProfile`` is the single source of truth for column kinds: validators,
planners and prompts all use the same inference, so an LLM never sees a
different picture of the data than the validators do.

Port constraints for ``dataframe`` (``TableConstraints``) map semantic *roles*
(response, predictors, time, ...) to the Params field that names the column(s).
"""

from __future__ import annotations

import warnings
from enum import StrEnum
from typing import Any, Literal

import pandas as pd
from pandas.api import types as ptypes
from pydantic import BaseModel, ConfigDict, Field

from .artifacts import ArtifactType
from .errors import ErrorDetail, suggest

# ------------------------------------------------------------------ profile


class ColumnKind(StrEnum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    TEXT = "text"


class ColumnProfile(BaseModel):
    name: str
    kind: ColumnKind
    dtype: str
    n_missing: int
    missing_ratio: float
    n_unique: int
    examples: list[str]


class DatasetProfile(BaseModel):
    n_rows: int
    n_cols: int
    columns: list[ColumnProfile]

    def column(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)

    def names(self, kind: ColumnKind | None = None) -> list[str]:
        return [c.name for c in self.columns if kind is None or c.kind == kind]

    def to_prompt(self, max_cols: int = 40) -> str:
        rows = [f"dataframe: rows={self.n_rows}, columns={self.n_cols}"]
        for c in self.columns[:max_cols]:
            rows.append(
                f"- {c.name}: {c.kind.value} (missing {c.missing_ratio:.0%}, unique {c.n_unique}, "
                f"e.g. {', '.join(c.examples)})"
            )
        if self.n_cols > max_cols:
            rows.append(f"... {self.n_cols - max_cols} more columns")
        return "\n".join(rows)


def _looks_datetime(s: pd.Series) -> bool:
    sample = s.dropna().astype(str).head(50)
    if sample.empty or sample.str.fullmatch(r"-?\d+(\.\d+)?").all():
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce")
    return parsed.notna().mean() >= 0.9


def infer_kind(s: pd.Series) -> ColumnKind:
    if ptypes.is_bool_dtype(s):
        return ColumnKind.BOOLEAN
    if ptypes.is_numeric_dtype(s):
        return ColumnKind.NUMERIC
    if ptypes.is_datetime64_any_dtype(s):
        return ColumnKind.DATETIME
    if isinstance(s.dtype, pd.CategoricalDtype):
        return ColumnKind.CATEGORICAL
    if _looks_datetime(s):
        return ColumnKind.DATETIME
    n = max(len(s.dropna()), 1)
    return ColumnKind.CATEGORICAL if s.nunique(dropna=True) <= max(20, 0.5 * n) else ColumnKind.TEXT


def profile_dataframe(df: pd.DataFrame) -> DatasetProfile:
    cols, n = [], len(df)
    for name in df.columns:
        s = df[name]
        miss = int(s.isna().sum())
        cols.append(
            ColumnProfile(
                name=str(name),
                kind=infer_kind(s),
                dtype=str(s.dtype),
                n_missing=miss,
                missing_ratio=round(miss / n, 4) if n else 0.0,
                n_unique=int(s.nunique(dropna=True)),
                examples=[str(v)[:20] for v in s.dropna().unique()[:3]],
            )
        )
    return DatasetProfile(n_rows=n, n_cols=df.shape[1], columns=cols)


def coerce_datetime(s: pd.Series) -> pd.Series:
    if infer_kind(s) == ColumnKind.DATETIME and not ptypes.is_datetime64_any_dtype(s):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.to_datetime(s, errors="coerce")
    return s


# ------------------------------------------------------------------ constraints

DType = Literal["numeric", "categorical", "datetime", "any"]


class ColumnRole(BaseModel):
    """Maps a semantic role (e.g. 'response') to the Params field holding the column name(s)."""

    model_config = ConfigDict(extra="forbid")

    role: str
    param: str
    dtype: DType = "any"
    multiple: bool = False
    min_count: int = Field(1, ge=0)
    max_count: int | None = None
    optional: bool = False
    max_missing_ratio: float = Field(0.3, ge=0, le=1)
    allow_constant: bool = False
    max_levels: int | None = Field(None, description="categorical only: maximum number of levels")


class TableConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_rows: int = Field(1, ge=1)
    roles: list[ColumnRole] = Field(default_factory=list)
    distinct_roles: bool = Field(True, description="a column may not play two roles at once")


def _kind_ok(kind: ColumnKind, required: str) -> bool:
    if required == "categorical":
        return kind in (ColumnKind.CATEGORICAL, ColumnKind.BOOLEAN)
    return kind.value == required


def role_columns(params: BaseModel, role: ColumnRole) -> list[str]:
    value = getattr(params, role.param, None)
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def used_columns(params: BaseModel, constraints: TableConstraints) -> list[str]:
    cols: list[str] = []
    for role in constraints.roles:
        cols += [c for c in role_columns(params, role) if c not in cols]
    return cols


class DataFrameType(ArtifactType):
    name = "dataframe"
    Constraints = TableConstraints
    python_types = (pd.DataFrame,)
    specificity = 2

    def profile(self, value: pd.DataFrame) -> DatasetProfile:
        return profile_dataframe(value)

    def static_check(  # ty: ignore[invalid-method-override]  # narrower profile/constraints types than the generic base
        self, profile: DatasetProfile, constraints: TableConstraints, params: BaseModel, loc: tuple[str | int, ...]
    ) -> list[ErrorDetail]:
        errors: list[ErrorDetail] = []
        seen: dict[str, str] = {}
        for role in constraints.roles:
            cols = role_columns(params, role)
            ploc = ("params", role.param)
            if not cols:
                if not role.optional and role.min_count > 0:
                    errors.append(ErrorDetail(loc=ploc, type="role_missing", msg=f"role '{role.role}' needs a column"))
                continue
            if len(cols) < role.min_count:
                errors.append(
                    ErrorDetail(
                        loc=ploc,
                        type="too_few_columns",
                        msg=f"role '{role.role}' needs at least {role.min_count} column(s), got {len(cols)}",
                    )
                )
            if role.max_count is not None and len(cols) > role.max_count:
                errors.append(
                    ErrorDetail(
                        loc=ploc,
                        type="too_many_columns",
                        msg=f"role '{role.role}' accepts at most {role.max_count} column(s), got {len(cols)}",
                    )
                )
            for col in cols:
                cp = profile.column(col)
                if cp is None:
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="column_not_found",
                            msg=f"column '{col}' does not exist",
                            input=col,
                            hint=suggest(col, profile.names()) or f"available: {profile.names()[:15]}",
                        )
                    )
                    continue
                if role.dtype != "any" and not _kind_ok(cp.kind, role.dtype):
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="wrong_dtype",
                            input=col,
                            msg=f"column '{col}' is {cp.kind.value}, role '{role.role}' requires {role.dtype}",
                            hint=f"{role.dtype} columns: {profile.names(ColumnKind(role.dtype))[:10]}",
                        )
                    )
                if cp.missing_ratio > role.max_missing_ratio:
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="too_many_missing",
                            input=col,
                            msg=f"column '{col}' is {cp.missing_ratio:.0%} missing (max {role.max_missing_ratio:.0%})",
                        )
                    )
                if role.max_levels and cp.kind == ColumnKind.CATEGORICAL and cp.n_unique > role.max_levels:
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="too_many_levels",
                            input=col,
                            msg=f"column '{col}' has {cp.n_unique} levels (max {role.max_levels})",
                        )
                    )
                if constraints.distinct_roles and col in seen and seen[col] != role.role:
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="duplicate_role",
                            input=col,
                            msg=f"column '{col}' is used as both '{seen[col]}' and '{role.role}'",
                        )
                    )
                seen.setdefault(col, role.role)
        if profile.n_rows < constraints.min_rows:
            errors.append(
                ErrorDetail(
                    loc=loc, type="too_few_rows", msg=f"{profile.n_rows} rows, at least {constraints.min_rows} required"
                )
            )
        return errors

    def runtime_check(  # ty: ignore[invalid-method-override]
        self, value: pd.DataFrame, constraints: TableConstraints, params: BaseModel, loc: tuple[str | int, ...]
    ) -> list[ErrorDetail]:
        errors: list[ErrorDetail] = []
        used = used_columns(params, constraints)
        complete = value[used].dropna() if used else value
        if used and len(complete) < constraints.min_rows:
            errors.append(
                ErrorDetail(
                    loc=loc,
                    type="too_few_complete_rows",
                    msg=f"only {len(complete)} complete rows for columns {used}; need {constraints.min_rows}",
                )
            )
        for role in constraints.roles:
            if role.allow_constant or role.dtype != "numeric":
                continue
            for col in role_columns(params, role):
                if complete[col].nunique() <= 1:
                    errors.append(
                        ErrorDetail(
                            loc=("params", role.param),
                            type="constant_column",
                            input=col,
                            msg=f"column '{col}' has zero variance",
                            hint="drop it from this role",
                        )
                    )
        return errors


class SeriesProfile(BaseModel):
    name: str | None
    length: int
    dtype: str

    def to_prompt(self) -> str:
        return f"series '{self.name}': length {self.length}, dtype {self.dtype}"


class SeriesType(ArtifactType):
    name = "series"
    python_types = (pd.Series,)
    specificity = 2

    def profile(self, value: pd.Series) -> SeriesProfile:
        return SeriesProfile(
            name=None if value.name is None else str(value.name), length=len(value), dtype=str(value.dtype)
        )


def register_tabular_types(types: Any) -> None:
    types.register(DataFrameType())
    types.register(SeriesType())


__all__ = [
    "ColumnKind",
    "ColumnProfile",
    "ColumnRole",
    "DType",
    "DataFrameType",
    "DatasetProfile",
    "SeriesProfile",
    "SeriesType",
    "TableConstraints",
    "coerce_datetime",
    "infer_kind",
    "profile_dataframe",
    "register_tabular_types",
    "role_columns",
    "used_columns",
]
