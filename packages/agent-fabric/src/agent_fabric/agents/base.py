"""Base agent: template method shared by every kind (budget, trace, fallback, memory)."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..errors import BudgetExceeded, FabricError
from ..llm.backends import LLMSettings
from ..llm.prompts import AGENT_SYSTEM, compact
from ..memory.base import RunSummary, memory_context, namespaced
from .runtime import AgentResult, AgentTask, MeteredBackend, RunContext, Status
from .spec import AgentSpec

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import AgentFabric


class BaseAgent(ABC):
    accepts_sub_agents: bool = False

    def __init__(
        self, name: str, spec: AgentSpec, fabric: AgentFabric, children: dict[str, BaseAgent] | None = None
    ) -> None:
        self.name, self.spec, self.fabric = name, spec, fabric
        self.children: dict[str, BaseAgent] = children or {}
        self.fallback_agent: BaseAgent | None = None

    # ------------------------------------------------------------------ template method
    def run(self, task: AgentTask, ctx: RunContext, parent_path: str = "", depth: int = 0) -> AgentResult:
        """Run the agent on a task: the template method every agent goes through.

        Records the start and end events, charges the run budget (``max_depth`` and ``max_agent_runs``) and calls the kind-specific ``_run``. A
        `BudgetExceeded` or other `FabricError` becomes a ``failed`` result carrying the located error; when a ``fallback`` backend is configured it is
        tried first and the fallback is noted in ``notes``. Records LLM calls and duration, and, when memory is configured, the instruction, the answer and a
        `RunSummary` under ``<session>/<path>``. Does not raise `FabricError`s: they end up in the result.
        """
        path = f"{parent_path}/{self.name}" if parent_path else self.name
        t0 = time.perf_counter()
        ctx.event(path, "start", task.instruction)
        try:
            ctx.budget.charge_run(path, depth)
            res = self._run(task, ctx, path, depth)
        except BudgetExceeded as exc:
            res = self.result(path, "failed", error=exc.report, summary=exc.message)
        except FabricError as exc:
            ctx.event(path, "error", f"{exc.category.value}: {exc.message}")
            if self.fallback_agent is None:
                res = self.result(path, "failed", error=exc.report, summary=exc.message)
            else:
                ctx.event(path, "fallback", self.fallback_agent.spec.backend)
                try:
                    res = self.fallback_agent._run(task, ctx, path, depth)
                    res.notes.append(
                        f"fell back to backend '{self.fallback_agent.spec.backend}' after "
                        f"{exc.category.value} error: {exc.message}"
                    )
                except FabricError as exc2:
                    res = self.result(
                        path,
                        "failed",
                        error=exc2.report,
                        summary=exc2.message,
                        notes=[f"primary failed: {exc.message}"],
                    )
        res.llm_calls = ctx.llm_calls_by_path.get(path, 0)
        res.duration_s = round(time.perf_counter() - t0, 4)
        ctx.event(path, "end", res.status)
        if ctx.memory is not None:
            ctx.memory.add_message(namespaced(ctx.session_id, path), "user", task.instruction)
            ctx.memory.add_message(namespaced(ctx.session_id, path), "assistant", res.summary or res.status)
            ctx.memory.remember_run(
                namespaced(ctx.session_id, path),
                RunSummary(
                    objective=task.instruction, agent=path, status={path: res.status}, headlines=[res.summary[:200]]
                ),
            )
        return res

    @abstractmethod
    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult: ...

    # ------------------------------------------------------------------ helpers
    @property
    def kind(self) -> str:
        """The agent kind (``supervisor``, ``planner``, ``pipeline``, ``llm`` or ``function``)."""
        return self.spec.kind

    @property
    def settings(self) -> LLMSettings:
        """`LLMSettings` for this agent: the run's settings with the agent's own model, temperature and retries applied."""
        return self.fabric.settings_for(self.spec)

    @property
    def model(self) -> str:
        """LiteLLM alias this agent uses (its own ``model``, else the default for its kind)."""
        return self.fabric.model_for(self.spec)

    def llm(self, ctx: RunContext, path: str) -> MeteredBackend:
        """The LLM backend for this agent, metered so every call is charged to the run budget and traced at ``path``."""
        return ctx.metered(self.fabric.llm_backend, path)

    def result(self, path: str, status: Status, **kw: Any) -> AgentResult:
        """Build an `AgentResult` for this agent at ``path`` with the given status and extra fields."""
        return AgentResult(agent=self.name, path=path, kind=self.kind, status=status, **kw)

    def system_prompt(self) -> str:
        """Role header (if any) followed by the AGENT.md body - the body is the primary instruction source."""
        s = self.spec
        parts = []
        if s.role or s.goal:
            parts.append(
                AGENT_SYSTEM.format(
                    role=s.role or self.name.replace("_", " "), goal=s.goal or s.card, backstory=s.backstory
                ).strip()
            )
        if s.instructions:
            parts.append(s.instructions)
        return "\n\n".join(parts) or f"You are the '{self.name}' agent."

    def input_keys(self, task: AgentTask, ctx: RunContext) -> list[str]:
        """Blackboard keys this agent reads: the task's own inputs, else the spec's ``inputs``, else every key the run started with."""
        return task.inputs or self.spec.inputs or list(ctx.input_keys)

    def describe_inputs(self, values: dict[str, Any]) -> str:
        """Describe input values for a prompt: JSON, number and ``any`` values are shown compacted (up to 2500 characters), other types through their artifact profile."""
        types = self.fabric.registry.types
        lines = []
        for key, v in values.items():
            t = types.infer(v)
            if t.name in ("json", "any", "number"):
                lines.append(f"[{key}] {compact(v, max_chars=2500)}")
            else:
                lines.append(f"[{key}] {t.describe(t.profile(v), v)}")
        return "\n".join(lines) or "(none)"

    def memory_context(self, ctx: RunContext, path: str) -> str:
        """Text of this agent's recent runs in the session, for routers and planners."""
        return memory_context(ctx.memory, namespaced(ctx.session_id, path))

    def card(self) -> dict[str, Any]:
        """Short description of the agent for parent routers: name, kind, role, what it does and, for supervisors, its sub-agents."""
        return {
            "name": self.name,
            "kind": self.kind,
            "role": self.spec.role,
            "does": self.spec.card,
            **({"sub_agents": sorted(self.children)} if self.children else {}),
        }


__all__ = [
    "BaseAgent",
]
