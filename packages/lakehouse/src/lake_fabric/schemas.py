"""Structured-output schemas used by lakehouse agents (register with ``AgentFabric.register_schema``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DagReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["approved", "changes_requested", "rejected"]
    summary: str = Field(min_length=3, max_length=400)
    issues: list[str] = Field(default_factory=list, max_length=8)


SCHEMAS = {"DagReview": DagReview}


__all__ = [
    "SCHEMAS",
    "DagReview",
]
