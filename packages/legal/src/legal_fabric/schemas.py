"""Structured-output schemas used by legal agents (register with ``AgentFabric.register_schema``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RebuttalPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_point_id: str = Field(description="id of the point in the dossier this answers, e.g. P3")
    weakness: str = Field(min_length=10, max_length=400, description="what is weak in the other side's point")
    counterargument: str = Field(min_length=20, max_length=1200)
    evidence: list[str] = Field(min_length=1, max_length=8, description="locators: 'ev12/DEPOIM1 p.3 l.10-14'")
    authorities: list[str] = Field(default_factory=list, max_length=4, description="authority ids for this point")
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=200, max_length=1500, description="one paragraph: why this path")


class Rebuttal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    summary: str = Field(min_length=20, max_length=800)
    points: list[RebuttalPoint] = Field(default_factory=list, max_length=12)
    needs_research: list[str] = Field(default_factory=list, description="point ids left without an authority")


SCHEMAS = {"Rebuttal": Rebuttal}

__all__ = ["SCHEMAS", "Rebuttal", "RebuttalPoint"]
