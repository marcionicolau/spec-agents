"""AgentFabric: validates an agent tree, builds it through registered builders and runs it.

    fabric = AgentFabric(registry, AgentsConfig.load("config")  # fabric.md + agents/*/AGENT.md)
    report = fabric.run("How do treatments affect yield?", inputs={"data": df})
    print(report.result.tree())

Extension points (no call-site changes):
    @AgentFabric.builder("reviewer", "fabric")          # new kind
    @AgentFabric.builder("planner", "my_rules")         # new backend for a kind
    fabric.register_schema("Review", ReviewModel)       # structured outputs
    fabric.register_function("fetch_weather", fn)       # function agents
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..errors import AgentConfigError, ErrorDetail, SpecError, suggest
from ..llm.backends import LLMBackend, LLMSettings
from ..memory.base import InMemoryMemory, MemoryPort
from .base import BaseAgent
from .runtime import AgentRunReport, AgentTask, Budget, RunContext
from .spec import AgentsConfig, AgentSpec

type Factory = Callable[["AgentFabric", str, AgentSpec, dict[str, BaseAgent]], BaseAgent]


@dataclass(frozen=True)
class BuilderInfo:
    factory: Factory
    accepts_sub_agents: bool
    requires: tuple[str, ...] = ()  # spec fields that must be set


class AgentFabric:
    """Builds and runs an agent tree from an `AgentsConfig` over a registry of components.

    Validates the tree (references, cycles, depth, capabilities) before the first run, builds one `BaseAgent` per node through the
    builder registry (one builder per ``(kind, backend)``) and runs the root agent with a bounded `RunContext`. Models, schemas and
    functions are referenced by name from the config and registered here. Use `run` to execute and `validate` to check without running.
    """

    _builders: dict[tuple[str, str], BuilderInfo] = {}

    def __init__(
        self,
        registry: Any,
        config: AgentsConfig,
        backend: LLMBackend | None = None,
        memory: MemoryPort | None = None,
        validate: bool = True,
    ) -> None:
        self.registry, self.config = registry, config
        self._backend = backend
        self.memory = memory if memory is not None else InMemoryMemory()
        self._schemas: dict[str, type[BaseModel]] = {}
        self._functions: dict[str, Callable[..., Any]] = {}
        self._agents: dict[str, BaseAgent] = {}
        self._validate, self._validated = validate, False
        for d in self.config.skill_dirs:  # code-free domains: plain SKILL.md directories
            p = Path(d)
            if not p.is_dir():
                raise AgentConfigError(
                    f"skills directory '{d}' does not exist",
                    [ErrorDetail(type="missing_skill_dir", msg=str(p), hint="fix 'skill_dirs' in fabric.md")],
                )
            self.registry.load_domain(p)

    # ------------------------------------------------------------ extension registries
    @classmethod
    def builder(
        cls, kind: str, backend: str = "fabric", *, accepts_sub_agents: bool = False, requires: tuple[str, ...] = ()
    ) -> Callable[[Factory], Factory]:
        def deco(fn: Factory) -> Factory:
            cls._builders[(kind, backend)] = BuilderInfo(fn, accepts_sub_agents, requires)
            return fn

        return deco

    @classmethod
    def kinds(cls) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for k, b in cls._builders:
            out.setdefault(k, []).append(b)
        return {k: sorted(v) for k, v in out.items()}

    def register_schema(self, name: str, model: type[BaseModel]) -> None:
        self._schemas[name] = model
        self._agents.clear()
        self._validated = False

    def register_function(self, name: str, fn: Callable[..., Any]) -> None:
        self._functions[name] = fn
        self._agents.clear()
        self._validated = False

    def schema(self, name: str) -> type[BaseModel]:
        if name not in self._schemas:
            raise SpecError(
                f"Unknown output schema '{name}'",
                [ErrorDetail(type="unknown_schema", msg=name, hint=suggest(name, self._schemas))],
            )
        return self._schemas[name]

    def function(self, name: str) -> Callable[..., Any]:
        if name not in self._functions:
            raise SpecError(
                f"Unknown function '{name}'",
                [ErrorDetail(type="unknown_function", msg=name, hint=suggest(name, self._functions))],
            )
        return self._functions[name]

    # ------------------------------------------------------------ LLM plumbing
    @property
    def llm_backend(self) -> LLMBackend:
        if self._backend is None:
            from ..llm.backends import LiteLLMProxyBackend

            self._backend = LiteLLMProxyBackend(self.config.llm)
        return self._backend

    def model_for(self, spec: AgentSpec) -> str:
        s = self.config.llm
        return spec.model or {"planner": s.planner_model, "supervisor": s.planner_model}.get(
            spec.kind, s.interpreter_model
        )

    def settings_for(self, spec: AgentSpec) -> LLMSettings:
        upd: dict[str, Any] = {}
        if spec.model:
            upd.update(planner_model=spec.model, interpreter_model=spec.model)
        if spec.temperature is not None:
            upd["temperature"] = spec.temperature
        if spec.max_retries is not None:
            upd["max_correction_attempts"] = spec.max_retries
        return self.config.llm.model_copy(update=upd)

    def pydantic_ai_model(self, spec: AgentSpec) -> Any:
        if "model_object" in spec.options:  # tests / custom providers
            return spec.options["model_object"]
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        s = self.config.llm
        return OpenAIChatModel(self.model_for(spec), provider=OpenAIProvider(base_url=s.base_url, api_key=s.api_key))

    # ------------------------------------------------------------ validation
    _LAZY: dict[tuple[str, str], str] = {("planner", "dspy"): "agent_fabric.integrations.dspy"}

    def _load_lazy_backends(self) -> None:
        import importlib

        for a in self.config.agents.values():
            for backend in (a.backend, a.fallback):
                mod = self._LAZY.get((a.kind, backend or ""))
                if mod and (a.kind, backend) not in self._builders:
                    with contextlib.suppress(ImportError):
                        importlib.import_module(mod)

    def validate(self) -> list[ErrorDetail]:
        self._load_lazy_backends()
        cfg, errors = self.config, []
        kinds = self.kinds()
        for name, a in cfg.agents.items():
            loc = ("agents", name)
            if a.kind not in kinds:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("kind",),
                        type="unknown_kind",
                        input=a.kind,
                        msg=f"no builder for kind '{a.kind}'",
                        hint=suggest(a.kind, kinds) or f"kinds: {sorted(kinds)}",
                    )
                )
                continue
            for field, backend in (("backend", a.backend), ("fallback", a.fallback)):
                if backend and (a.kind, backend) not in self._builders:
                    errors.append(
                        ErrorDetail(
                            loc=loc + (field,),
                            type="unknown_backend",
                            input=backend,
                            msg=f"kind '{a.kind}' has no backend '{backend}'",
                            hint=suggest(backend, kinds[a.kind]) or f"backends: {kinds[a.kind]}",
                        )
                    )
            info = self._builders.get((a.kind, a.backend))
            if info is None:
                continue
            if a.sub_agents and not info.accepts_sub_agents:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("sub_agents",),
                        type="sub_agents_not_allowed",
                        msg=f"kind '{a.kind}' cannot own sub-agents",
                        hint="use kind: supervisor",
                    )
                )
            if info.accepts_sub_agents and not a.sub_agents:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("sub_agents",), type="no_sub_agents", msg="a supervisor needs at least one sub-agent"
                    )
                )
            for i, child in enumerate(a.sub_agents):
                if child == name:
                    errors.append(
                        ErrorDetail(
                            loc=loc + ("sub_agents", i),
                            type="self_reference",
                            msg="an agent cannot be its own sub-agent",
                        )
                    )
                elif child not in cfg.agents:
                    errors.append(
                        ErrorDetail(
                            loc=loc + ("sub_agents", i),
                            type="unknown_agent",
                            input=child,
                            msg=f"sub-agent '{child}' is not declared",
                            hint=suggest(child, cfg.agents),
                        )
                    )
            if len(set(a.sub_agents)) != len(a.sub_agents):
                errors.append(ErrorDetail(loc=loc + ("sub_agents",), type="duplicate", msg="sub-agent listed twice"))
            for field in info.requires:
                if not getattr(a, field):
                    errors.append(
                        ErrorDetail(loc=loc + (field,), type="missing", msg=f"kind '{a.kind}' requires '{field}'")
                    )
            if a.pipeline and a.pipeline not in self.registry.pipelines():
                errors.append(
                    ErrorDetail(
                        loc=loc + ("pipeline",),
                        type="unknown_pipeline",
                        input=a.pipeline,
                        msg=f"pipeline '{a.pipeline}' is not registered",
                        hint=suggest(a.pipeline, self.registry.pipelines())
                        or f"available: {self.registry.pipelines()}",
                    )
                )
            if a.function and a.function not in self._functions:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("function",),
                        type="unknown_function",
                        input=a.function,
                        msg=f"function '{a.function}' is not registered",
                        hint=suggest(a.function, self._functions),
                    )
                )
            if a.output_schema and a.output_schema not in self._schemas:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("output_schema",),
                        type="unknown_schema",
                        input=a.output_schema,
                        msg=f"schema '{a.output_schema}' is not registered",
                        hint=suggest(a.output_schema, self._schemas),
                    )
                )
            for d in a.domains:
                if d not in self.registry.domains():
                    errors.append(
                        ErrorDetail(
                            loc=loc + ("domains",),
                            type="unknown_domain",
                            input=d,
                            msg=f"domain '{d}' has no components",
                            hint=suggest(d, self.registry.domains()) or f"domains: {self.registry.domains()}",
                        )
                    )
        if errors:
            return errors
        # cycles and depth over the sub-agent graph
        state: dict[str, int] = {}
        depth: dict[str, int] = {}

        def visit(n: str, trail: tuple[str, ...]) -> int:
            if state.get(n) == 1:
                errors.append(
                    ErrorDetail(
                        loc=("agents", n, "sub_agents"),
                        type="cycle",
                        msg=" -> ".join(trail + (n,)),
                        hint="an agent may not (indirectly) delegate to its own ancestor",
                    )
                )
                return 0
            if state.get(n) == 2:
                return depth[n]
            state[n] = 1
            depth[n] = 1 + max((visit(c, trail + (n,)) for c in cfg.agents[n].sub_agents), default=-1)
            state[n] = 2
            return depth[n]

        for r in cfg.roots() or list(cfg.agents):
            visit(r, ())
        for n in cfg.agents:  # agents only reachable through a cycle
            if n not in state:
                visit(n, ())
        if not errors:
            for r in cfg.roots():
                if depth[r] > cfg.budget.max_depth:
                    errors.append(
                        ErrorDetail(
                            loc=("agents", r),
                            type="too_deep",
                            msg=f"tree under '{r}' is {depth[r]} levels deep (max_depth {cfg.budget.max_depth})",
                            hint="flatten the hierarchy or raise budget.max_depth",
                        )
                    )
        return errors

    # ------------------------------------------------------------ building
    def build(self, name: str) -> BaseAgent:
        if self._validate and not self._validated:
            errs = self.validate()
            if errs:
                raise AgentConfigError(f"Agent tree has {len(errs)} problem(s)", errs)
            self._validated = True
        if name not in self.config.agents:
            raise AgentConfigError(
                f"Unknown agent '{name}'",
                [ErrorDetail(type="unknown_agent", msg=name, hint=suggest(name, self.config.agents))],
            )
        if name not in self._agents:
            spec = self.config.agents[name]
            children = {c: self.build(c) for c in spec.sub_agents}
            self._agents[name] = self._make(name, spec, children)
        return self._agents[name]

    def _make(self, name: str, spec: AgentSpec, children: dict[str, BaseAgent]) -> BaseAgent:
        try:
            agent = self._builders[(spec.kind, spec.backend)].factory(self, name, spec, children)
        except Exception:
            if not spec.fallback:
                raise
            return self._make(name, spec.model_copy(update={"backend": spec.fallback, "fallback": None}), children)
        if spec.fallback:
            fb_spec = spec.model_copy(update={"backend": spec.fallback, "fallback": None})
            try:
                agent.fallback_agent = self._builders[(spec.kind, spec.fallback)].factory(self, name, fb_spec, children)
            except Exception:  # pragma: no cover - fallback unusable is not fatal at build time
                agent.fallback_agent = None
        return agent

    # ------------------------------------------------------------ running
    def run(
        self,
        instruction: str,
        inputs: dict[str, Any] | None = None,
        *,
        root: str | None = None,
        session_id: str = "default",
        on_event: Any = None,
        on_step: Any = None,
    ) -> AgentRunReport:
        roots = [root] if root else self.config.roots()
        if len(roots) != 1:
            raise AgentConfigError(
                "Cannot determine the root agent",
                [
                    ErrorDetail(
                        loc=("root",),
                        type="ambiguous_root",
                        msg=f"candidates: {roots}",
                        hint="set 'root' in the config or pass root=...",
                    )
                ],
            )
        agent = self.build(roots[0])
        ctx = RunContext(
            session_id=session_id,
            budget=Budget(self.config.budget),
            memory=self.memory,
            blackboard=dict(inputs or {}),
            input_keys=list(inputs or {}),
            on_event=on_event,
            on_step=on_step,
        )
        result = agent.run(AgentTask(instruction=instruction), ctx)
        report = AgentRunReport(
            session_id=session_id, instruction=instruction, result=result, trace=ctx.trace, usage=ctx.budget.usage()
        )
        report._blackboard = ctx.blackboard
        return report


# ============================================================================ built-in builders
from . import kinds as _k  # noqa: E402


@AgentFabric.builder("llm", "fabric")
def _llm(f: AgentFabric, name: str, spec: AgentSpec, children: dict) -> BaseAgent:
    return _k.LLMWorkerAgent(name, spec, f)


@AgentFabric.builder("function", "fabric", requires=("function",))
def _function(f: AgentFabric, name: str, spec: AgentSpec, children: dict) -> BaseAgent:
    return _k.FunctionAgent(name, spec, f)


@AgentFabric.builder("pipeline", "fabric", requires=("pipeline",))
def _pipeline(f: AgentFabric, name: str, spec: AgentSpec, children: dict) -> BaseAgent:
    return _k.PipelineAgent(name, spec, f)


@AgentFabric.builder("supervisor", "fabric", accepts_sub_agents=True)
@AgentFabric.builder("supervisor", "rules", accepts_sub_agents=True)
def _supervisor(f: AgentFabric, name: str, spec: AgentSpec, children: dict) -> BaseAgent:
    return _k.SupervisorAgent(name, spec, f, children)


@AgentFabric.builder("supervisor", "pydantic_ai", accepts_sub_agents=True)
def _supervisor_pai(f: AgentFabric, name: str, spec: AgentSpec, children: dict) -> BaseAgent:
    import pydantic_ai  # noqa: F401  (fail at build time -> fallback)

    return _k.PydanticAISupervisor(name, spec, f, children)


def planner_builder(backend: str, make: Callable[[AgentFabric, AgentSpec, LLMBackend], Any]) -> None:
    """Register a planner backend: ``make(fabric, spec, metered_backend) -> Planner``."""

    @AgentFabric.builder("planner", backend)
    def _build(f: AgentFabric, name: str, spec: AgentSpec, children: dict) -> BaseAgent:
        return _k.PlannerAgent(name, spec, f, planner_factory=lambda backend: make(f, spec, backend))


def _make_llm_planner(f: AgentFabric, spec: AgentSpec, backend: LLMBackend) -> Any:
    from ..llm.planner import LLMPlanner

    return LLMPlanner(backend, f.registry, f.settings_for(spec), spec.domains or None)


def _make_pai_planner(f: AgentFabric, spec: AgentSpec, backend: LLMBackend) -> Any:
    from ..llm.planner import PydanticAIPlanner

    return PydanticAIPlanner(
        f.registry, f.settings_for(spec), model=spec.options.get("model_object"), domains=spec.domains or None
    )


def _make_template_planner(f: AgentFabric, spec: AgentSpec, backend: LLMBackend) -> Any:
    from ..llm.planner import TemplatePlanner

    return TemplatePlanner(f.registry, spec.pipeline or spec.options["pipeline"], spec.options.get("params"))


planner_builder("fabric", _make_llm_planner)
planner_builder("pydantic_ai", _make_pai_planner)
planner_builder("template", _make_template_planner)


__all__ = [
    "AgentFabric",
    "BuilderInfo",
    "planner_builder",
]
