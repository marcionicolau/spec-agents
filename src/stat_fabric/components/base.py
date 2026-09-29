"""Base for statistics components: a component whose main input port is a ``dataframe``."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field

from agent_fabric.component import Component, ComponentParams, ComponentResult, Num, StepContext
from agent_fabric.errors import ErrorDetail

__all__ = ["ComponentParams", "Num", "StepContext", "TableComponent", "TableResult"]


class TableResult(ComponentResult):
    n_used: int = Field(0, description="rows actually used after dropping missing values")


class TableComponent[P: ComponentParams, R: TableResult](Component[P, R]):
    data_port: ClassVar[str] = "data"

    @property
    def min_rows(self) -> int:
        return self.port_constraints[self.data_port].min_rows

    def compute(self, inputs: dict[str, Any], params: P, ctx: StepContext) -> R:
        return self.compute_table(inputs.get(self.data_port), params, ctx, inputs)

    @abstractmethod
    def compute_table(self, df: pd.DataFrame | None, params: P, ctx: StepContext, inputs: dict[str, Any]) -> R: ...

    def extra_checks(self, inputs: dict[str, Any], params: P) -> list[ErrorDetail]:
        df = inputs.get(self.data_port)
        return self.extra_data_checks(df, params) if df is not None else []

    def extra_data_checks(self, df: pd.DataFrame, params: P) -> list[ErrorDetail]:
        return []
