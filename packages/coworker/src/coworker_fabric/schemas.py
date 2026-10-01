"""Structured-output schemas used by coworker agents (register with ``AgentFabric.register_schema``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    line: int | None = None
    priority: Literal["high", "medium", "low"]
    change: str = Field(min_length=3, max_length=300)


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=3, max_length=400)
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=8)


SCHEMAS = {"Critique": Critique}


__all__ = [
    "SCHEMAS",
    "Critique",
    "Suggestion",
]
