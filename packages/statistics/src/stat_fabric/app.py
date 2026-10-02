"""Facade for the statistics domain on top of the generic agent fabric.

fabric = StatisticalAnalysisFabric.from_config("config", domains=[text_pack.register])  # AGENT.md tree
report = fabric.analyze(df, "Which treatments raise yield?", session_id="trial-2026")
print(render_markdown(report))
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentRunReport, AgentsConfig, AgentSpec
from agent_fabric.llm.backends import LLMBackend
from agent_fabric.memory import MemoryPort

from .domain import register
from .schemas import SCHEMAS

DEFAULT_CONFIG = AgentsConfig(
    root="statistician",
    agents={
        "statistician": AgentSpec(
            kind="planner",
            backend="fabric",
            fallback="stats_rules",
            domains=["statistics"],
            role="Senior statistician",
            goal="Plan and run the smallest valid statistical pipeline",
            interpret="rules",
            options={"repair": True},
        ),
    },
)


class StatisticalAnalysisFabric:
    """Facade over the generic fabric for statistical analysis.

    ``from_config(path, domains=...)`` loads an agent tree (default: one ``statistician`` planner with a rules fallback); ``analyze(df, question)``
    runs it on a DataFrame and returns an `AgentRunReport`.
    """

    def __init__(
        self,
        config: AgentsConfig | None = None,
        *,
        backend: LLMBackend | None = None,
        memory: MemoryPort | None = None,
        registry: Any = None,
    ) -> None:
        self.registry = registry or build_registry([register])
        self.agents = AgentFabric(self.registry, config or DEFAULT_CONFIG, backend=backend, memory=memory)
        for name, model in SCHEMAS.items():
            self.agents.register_schema(name, model)

    @classmethod
    def from_config(cls, path: str | Path, domains: Iterable[Callable] = (), **kw: Any) -> StatisticalAnalysisFabric:
        """Build the fabric from a config path.

        ``path``: agents directory (fabric.md + agents/*/AGENT.md) or legacy YAML file.
        ``domains``: extra domain packs the tree needs besides statistics.
        """
        return cls(AgentsConfig.load(path), registry=build_registry([register, *domains]), **kw)

    def analyze(
        self,
        df: pd.DataFrame,
        objective: str,
        *,
        session_id: str = "default",
        root: str | None = None,
        extra_inputs: dict[str, Any] | None = None,
    ) -> AgentRunReport:
        """Run the agent tree on a DataFrame and a question; returns the `AgentRunReport`.

        The frame is bound to the ``data`` input (``extra_inputs`` add more, e.g. ``notes``); ``root`` picks the root agent when the config has
        several candidates and ``session_id`` selects the memory session.
        """
        return self.agents.run(objective, {"data": df, **(extra_inputs or {})}, root=root, session_id=session_id)


__all__ = [
    "StatisticalAnalysisFabric",
]
