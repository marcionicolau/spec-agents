"""Runtime state shared by an agent tree during one run.

* **Blackboard** - named values: user inputs (``data``, ``text``...) and agent outputs
  (``<path>`` for an agent's output, ``<path>.<artifact>`` for its artifacts).
* **Budget**     - hard limits on depth, agent runs, delegations and LLM calls for the
  whole tree; exceeding one raises ``BudgetExceeded`` (never retried).
* **Trace**      - ordered events with agent paths (``lead/stats_team/planner``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ..errors import BudgetExceeded, DependencyError, ErrorDetail, ErrorReport, suggest
from ..llm.backends import LLMBackend, Message
from ..memory.base import MemoryPort

Status = Literal["ok", "partial", "failed", "skipped"]


class AgentTask(BaseModel):
    instruction: str = Field(min_length=1)
    inputs: list[str] = Field(default_factory=list, description="blackboard keys handed to the agent")


class TraceEvent(BaseModel):
    at: float
    path: str
    event: Literal["start", "end", "llm_call", "delegate", "fallback", "skip", "error"]
    detail: str = ""


class AgentResult(BaseModel):
    agent: str
    path: str
    kind: str
    status: Status
    summary: str = ""
    output: Any = None
    artifacts: list[str] = Field(default_factory=list, description="blackboard keys written by this agent")
    error: ErrorReport | None = None
    notes: list[str] = Field(default_factory=list)
    children: list["AgentResult"] = Field(default_factory=list)
    llm_calls: int = 0
    duration_s: float = 0.0

    def walk(self) -> Iterator["AgentResult"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def find(self, path: str) -> "AgentResult":
        for r in self.walk():
            if r.path == path or r.path.endswith("/" + path) or r.agent == path:
                return r
        raise KeyError(path)

    def tree(self, indent: int = 0) -> str:
        line = f"{'  ' * indent}- {self.agent} [{self.kind}] {self.status}: {self.summary[:100]}"
        return "\n".join([line] + [c.tree(indent + 1) for c in self.children])


class BudgetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_depth: int = Field(5, ge=1, le=20, description="root is depth 0")
    max_agent_runs: int = Field(60, ge=1)
    max_delegations: int = Field(25, ge=0)
    max_llm_calls: int = Field(60, ge=0)


class Budget:
    def __init__(self, s: BudgetSettings) -> None:
        self.s = s
        self.agent_runs = self.delegations = self.llm_calls = 0
        self.exhausted: str | None = None  # name of the first limit hit; supervisors stop delegating

    def _exceeded(self, what: str, limit: int, path: str) -> BudgetExceeded:
        self.exhausted = self.exhausted or what
        return BudgetExceeded(f"{what} budget exhausted ({limit}) at '{path}'",
                              [ErrorDetail(loc=("budget", what), type="budget_exceeded", msg=f"limit {limit} reached",
                                           hint=f"raise budget.{what} in the agents config or simplify the tree")])

    def charge_run(self, path: str, depth: int) -> None:
        if depth > self.s.max_depth:
            raise self._exceeded("max_depth", self.s.max_depth, path)
        self.agent_runs += 1
        if self.agent_runs > self.s.max_agent_runs:
            raise self._exceeded("max_agent_runs", self.s.max_agent_runs, path)

    def charge_delegation(self, path: str, n: int = 1) -> None:
        self.delegations += n
        if self.delegations > self.s.max_delegations:
            raise self._exceeded("max_delegations", self.s.max_delegations, path)

    def charge_llm(self, path: str, n: int = 1) -> None:
        self.llm_calls += n
        if self.llm_calls > self.s.max_llm_calls:
            raise self._exceeded("max_llm_calls", self.s.max_llm_calls, path)

    def usage(self) -> dict[str, int]:
        return {"agent_runs": self.agent_runs, "delegations": self.delegations, "llm_calls": self.llm_calls}


@dataclass
class RunContext:
    session_id: str
    budget: Budget
    memory: MemoryPort | None = None
    blackboard: dict[str, Any] = field(default_factory=dict)
    trace: list[TraceEvent] = field(default_factory=list)
    input_keys: list[str] = field(default_factory=list)
    llm_calls_by_path: dict[str, int] = field(default_factory=dict)
    t0: float = field(default_factory=time.perf_counter)

    def event(self, path: str, event: str, detail: str = "") -> None:
        self.trace.append(TraceEvent(at=round(time.perf_counter() - self.t0, 4), path=path, event=event, detail=detail[:200]))

    def put(self, key: str, value: Any) -> str:
        self.blackboard[key] = value
        return key

    def collect(self, keys: list[str]) -> dict[str, Any]:
        missing = [k for k in keys if k not in self.blackboard]
        if missing:
            raise DependencyError(f"blackboard keys not available: {missing}",
                                  [ErrorDetail(loc=("inputs",), type="missing_input", input=k, msg=f"'{k}' is not on the blackboard",
                                               hint=suggest(k, self.blackboard) or f"available: {sorted(self.blackboard)[:15]}")
                                   for k in missing])
        return {k: self.blackboard[k] for k in keys}

    def metered(self, backend: LLMBackend, path: str) -> "MeteredBackend":
        return MeteredBackend(backend, self, path)


class MeteredBackend:
    """Wraps an LLMBackend: charges the tree budget and traces every call."""

    def __init__(self, inner: LLMBackend, ctx: RunContext, path: str) -> None:
        self.inner, self.ctx, self.path = inner, ctx, path

    def complete(self, messages: list[Message], *, model: str | None = None, json_mode: bool = False,
                 temperature: float | None = None) -> str:
        self.ctx.budget.charge_llm(self.path)
        self.ctx.llm_calls_by_path[self.path] = self.ctx.llm_calls_by_path.get(self.path, 0) + 1
        self.ctx.event(self.path, "llm_call", model or "")
        return self.inner.complete(messages, model=model, json_mode=json_mode, temperature=temperature)


class AgentRunReport(BaseModel):
    session_id: str
    instruction: str
    result: AgentResult
    trace: list[TraceEvent]
    usage: dict[str, int]
    _blackboard: dict[str, Any] = PrivateAttr(default_factory=dict)

    @property
    def blackboard(self) -> dict[str, Any]:
        return self._blackboard

    @property
    def ok(self) -> bool:
        return self.result.status == "ok"
