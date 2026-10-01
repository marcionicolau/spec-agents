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
        return self.spec.kind

    @property
    def settings(self) -> LLMSettings:
        return self.fabric.settings_for(self.spec)

    @property
    def model(self) -> str:
        return self.fabric.model_for(self.spec)

    def llm(self, ctx: RunContext, path: str) -> MeteredBackend:
        return ctx.metered(self.fabric.llm_backend, path)

    def result(self, path: str, status: Status, **kw: Any) -> AgentResult:
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
        return task.inputs or self.spec.inputs or list(ctx.input_keys)

    def describe_inputs(self, values: dict[str, Any]) -> str:
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
        return memory_context(ctx.memory, namespaced(ctx.session_id, path))

    def card(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "role": self.spec.role,
            "does": self.spec.card,
            **({"sub_agents": sorted(self.children)} if self.children else {}),
        }
