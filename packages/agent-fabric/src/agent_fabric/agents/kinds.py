"""Built-in agent kinds.

``LLMWorkerAgent``   free text or structured output (``output_schema``) with grounding
``PipelineAgent``    runs a registered PipelineSpec deterministically
``PlannerAgent``     plans a pipeline over its domains (LLM / PydanticAI / DSPy / template / rules), executes it
``FunctionAgent``    wraps a registered Python callable (deterministic tool-like sub-agent)
``SupervisorAgent``  owns sub-agents; strategies: ``sequential`` | ``router`` (LLM delegation plan)
``PydanticAISupervisor`` delegation through PydanticAI tool calls
"""

from __future__ import annotations

import json
from typing import Any
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import (
    DataValidationError,
    DelegationError,
    DependencyError,
    ErrorDetail,
    ErrorReport,
    FabricError,
    LLMOutputError,
    details_from_pydantic,
    suggest,
)
from ..executor import PipelineExecutor, PipelineReport, StepStatus
from ..llm.backends import LLMBackend
from ..llm.interpreter import LLMInterpreter, RuleInterpreter, grounding_errors_texts
from ..llm.planner import Planner
from ..llm.prompts import ROUTER_RULES, SYNTHESIS_RULES, WORKER_JSON_RULES, compact
from ..llm.repair import LLMParamRepairer
from ..llm.self_correction import extract_text, structured_completion
from ..pipeline import PipelineInputs, parse_plan, types_compatible
from .base import BaseAgent
from .runtime import AgentResult, AgentTask, RunContext


def _string_fields(obj: Any, loc: tuple = ()) -> list[tuple[tuple, str]]:
    if isinstance(obj, str):
        return [(loc, obj)]
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in _string_fields(v, loc + (k,))]
    if isinstance(obj, list):
        return [x for i, v in enumerate(obj) for x in _string_fields(v, loc + (i,))]
    return []


def _structured_or_text(
    agent: BaseAgent, ctx: RunContext, path: str, system: str, user: str, grounding_sources: list[Any] | None
) -> Any:
    """Shared by workers and supervisors: schema output (validated) or free text, both grounded."""
    schema = agent.fabric.schema(agent.spec.output_schema) if agent.spec.output_schema else None
    check = agent.spec.options.get("check_grounding", grounding_sources is not None)

    def ground(value: Any) -> None:
        if check and grounding_sources is not None:
            errs = grounding_errors_texts(_string_fields(value), *grounding_sources)
            if errs:
                raise LLMOutputError("Answer cites numbers not present in the sources", errs)

    if schema is not None:
        system = f"{system}\n\n{WORKER_JSON_RULES.format(schema=json.dumps(schema.model_json_schema()))}"

        def parse(data: Any) -> dict[str, Any]:
            value = schema.model_validate(data).model_dump(mode="json")
            ground(value)
            return value

        return structured_completion(
            agent.llm(ctx, path),
            system,
            user,
            parse,
            model=agent.model,
            max_attempts=agent.settings.max_correction_attempts,
            json_mode=agent.settings.json_mode,
            temperature=agent.settings.temperature,
        ).value

    def parse_text(text: str) -> dict[str, Any]:
        ground(text)
        return {"text": text}

    return structured_completion(
        agent.llm(ctx, path),
        system,
        user,
        parse_text,
        model=agent.model,
        max_attempts=agent.settings.max_correction_attempts,
        json_mode=False,
        temperature=agent.settings.temperature,
        extract=extract_text,
    ).value


def _summary_of(output: Any) -> str:
    if isinstance(output, dict):
        for k in ("summary", "headline", "answer", "text"):
            if isinstance(output.get(k), str):
                return output[k][:300]
    return compact(output, max_chars=300)


# ============================================================================ leaf kinds


class LLMWorkerAgent(BaseAgent):
    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult:
        values = ctx.collect(self.input_keys(task, ctx)) if (task.inputs or self.spec.inputs) else {}
        user = f"Task: {task.instruction}\n\nInputs:\n{self.describe_inputs(values)}"
        mem = self.memory_context(ctx, path)
        if mem:
            user += f"\n\nYour previous work in this session:\n{mem}"
        sources = [values, task.instruction] if self.spec.options.get("check_grounding") else None
        output = _structured_or_text(self, ctx, path, self.system_prompt(), user, sources)
        return self.result(path, "ok", output=output, summary=_summary_of(output), artifacts=[ctx.put(path, output)])


class FunctionAgent(BaseAgent):
    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult:
        fn = self.fabric.function(self.spec.function or "")
        values = ctx.collect(self.input_keys(task, ctx))
        try:
            output = fn(task, values)
        except FabricError:
            raise
        except Exception as exc:
            raise DependencyError(
                f"function '{self.spec.function}' raised {type(exc).__name__}",
                [ErrorDetail(type=type(exc).__name__, msg=str(exc)[:300])],
            ) from exc
        return self.result(path, "ok", output=output, summary=_summary_of(output), artifacts=[ctx.put(path, output)])


class _PipelineRunner(BaseAgent):
    """Shared execution + interpretation for pipeline and planner agents."""

    def pipeline_inputs(self, task: AgentTask, ctx: RunContext, declared: dict | None = None) -> PipelineInputs:
        mapping: dict[str, str] = dict(self.spec.options.get("input_map", {}))
        keys = self.input_keys(task, ctx)
        values = ctx.collect(keys)
        named = {k.split(".")[-1].split("/")[-1]: v for k, v in values.items()}
        named.update({name: ctx.collect([key])[key] for name, key in mapping.items()})
        types = self.fabric.registry.types
        if not declared:
            return PipelineInputs.from_values(named, types)
        chosen = {k: v for k, v in named.items() if k in declared}
        spare = {k: v for k, v in named.items() if k not in declared}
        errors = []
        for name, port in declared.items():
            if name in chosen:
                continue
            fits = [k for k, v in spare.items() if types_compatible(types.infer(v).name, port.type)]
            if len(fits) == 1:  # unambiguous: bind by type
                chosen[name] = spare.pop(fits[0])
            elif port.required:
                errors.append(
                    ErrorDetail(
                        loc=("inputs", name),
                        type="missing_pipeline_input",
                        msg=f"pipeline input '{name}' ({port.type}) not provided"
                        + (f"; ambiguous candidates {fits}" if fits else ""),
                        hint="pass it in task inputs or map it with options.input_map",
                    )
                )
        if errors:
            raise DataValidationError("Pipeline inputs are incomplete", errors)
        return PipelineInputs(declared, chosen, types)

    def execute_and_report(
        self, plan: Any, pin: PipelineInputs, ctx: RunContext, path: str, extra: dict[str, Any]
    ) -> AgentResult:
        repairer = (
            LLMParamRepairer(self.llm(ctx, path), self.fabric.registry, self.settings)
            if self.spec.options.get("repair", False)
            else None
        )
        report: PipelineReport = PipelineExecutor(
            self.fabric.registry,
            repairer=repairer,
            fail_policy=self.spec.options.get("fail_policy", "continue"),
            llm=self.llm(ctx, path),
            llm_settings=self.settings,
            on_step=ctx.on_step,
        ).run(plan, pin)
        interps = self.interpret(report, plan.objective, ctx, path)
        artifacts = [ctx.put(f"{path}.{name}", value) for name, value in report.output_values().items()]
        output = {
            **extra,
            "steps": {o.step_id: o.status.value for o in report.outcomes},
            "results": {o.step_id: o.result for o in report.outcomes if o.result is not None},
            "interpretations": interps,
            "failures": {o.step_id: o.error.to_llm_feedback() for o in report.failures() if o.error},
        }
        artifacts.insert(0, ctx.put(path, output))
        heads = [i["headline"] for i in interps]
        summary = (
            " | ".join(heads[:4]) or f"{sum(o.status.value in ('ok', 'repaired') for o in report.outcomes)} step(s) ok"
        )
        status = "ok" if report.ok else ("partial" if any(o.result for o in report.outcomes) else "failed")
        err = None
        if not report.ok:
            err = DependencyError(
                f"{len(report.failures())} pipeline step(s) did not succeed",
                [
                    d.model_copy(update={"loc": ("steps", o.step_id) + d.loc})
                    for o in report.failures()
                    if o.error
                    for d in o.error.details[:3]
                ],
            ).report
        return self.result(path, status, output=output, summary=summary, artifacts=artifacts, error=err)

    def interpret(self, report: PipelineReport, objective: str, ctx: RunContext, path: str) -> list[dict[str, Any]]:
        mode = self.spec.interpret
        if mode == "none":
            return []
        rules = RuleInterpreter()
        llm = LLMInterpreter(self.llm(ctx, path), self.settings) if mode == "llm" else None
        out = []
        for o in report.outcomes:
            if o.status not in (StepStatus.OK, StepStatus.REPAIRED):
                continue
            it = None
            if llm is not None:
                try:
                    it = llm.interpret(o, objective, self.fabric.registry)
                except FabricError as exc:
                    if exc.category.value == "budget":
                        raise
                    ctx.event(path, "fallback", f"rule interpretation for {o.step_id}")
            it = it or rules.interpret(o, objective, self.fabric.registry)
            if it:
                out.append(it.model_dump())
        return out


class PipelineAgent(_PipelineRunner):
    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult:
        pspec = self.fabric.registry.pipeline(self.spec.pipeline or "")
        pin = self.pipeline_inputs(task, ctx, pspec.inputs)
        raw = pspec.instantiate(self.spec.options.get("params", {}))
        raw["objective"] = task.instruction if len(task.instruction) >= 3 else raw["objective"]
        plan = parse_plan(raw, self.fabric.registry, pin)
        return self.execute_and_report(plan, pin, ctx, path, {"pipeline": pspec.name})


class PlannerAgent(_PipelineRunner):
    def __init__(self, *a: Any, planner_factory: Callable[[LLMBackend], Planner], **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.planner_factory = planner_factory

    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult:
        pin = self.pipeline_inputs(task, ctx)
        planner = self.planner_factory(self.llm(ctx, path))
        outcome = planner.plan(task.instruction, pin, self.memory_context(ctx, path))
        if getattr(planner, "name", "") == "pydantic_ai":  # calls not seen by MeteredBackend
            ctx.budget.charge_llm(path, outcome.attempts)
            ctx.llm_calls_by_path[path] = ctx.llm_calls_by_path.get(path, 0) + outcome.attempts
        res = self.execute_and_report(
            outcome.plan,
            pin,
            ctx,
            path,
            {
                "planner": outcome.planner,
                "plan": outcome.plan.model_dump(),
                "rejected_plans": [r.to_llm_feedback() for r in outcome.rejected],
            },
        )
        if outcome.rejected:
            res.notes.append(f"planner self-corrected {len(outcome.rejected)} time(s)")
        return res


# ============================================================================ supervisors


class Delegation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,19}$")
    agent: str
    instruction: str = Field(min_length=3)
    inputs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class DelegationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str = ""
    delegations: list[Delegation] = Field(min_length=1)


def delegation_errors(plan: DelegationPlan, children: list[str], keys: list[str], max_n: int) -> list[ErrorDetail]:
    errors: list[ErrorDetail] = []
    ids = [d.id for d in plan.delegations]
    if len(ids) > max_n:
        errors.append(
            ErrorDetail(
                loc=("delegations",),
                type="too_many_delegations",
                msg=f"{len(ids)} delegations, at most {max_n} allowed",
                hint="merge related work",
            )
        )
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(ErrorDetail(loc=("delegations",), type="duplicate_id", msg=f"id '{dup}' used twice"))
    for i, d in enumerate(plan.delegations):
        loc = ("delegations", i)
        if d.agent not in children:
            errors.append(
                ErrorDetail(
                    loc=loc + ("agent",),
                    type="unknown_agent",
                    input=d.agent,
                    msg=f"'{d.agent}' is not one of your sub-agents",
                    hint=suggest(d.agent, children) or f"use one of {children}",
                )
            )
        for dep in d.depends_on:
            if dep not in ids or dep == d.id:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("depends_on",),
                        type="unknown_dependency",
                        input=dep,
                        msg=f"'{dep}' is not another delegation id",
                        hint=suggest(dep, ids),
                    )
                )
        for key in d.inputs:
            if key.startswith("@"):
                if key[1:] not in ids or key[1:] == d.id:
                    errors.append(
                        ErrorDetail(
                            loc=loc + ("inputs",),
                            type="unknown_reference",
                            input=key,
                            msg=f"'{key}' does not name another delegation",
                            hint=suggest(key[1:], ids),
                        )
                    )
            elif key not in keys:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("inputs",),
                        type="unknown_key",
                        input=key,
                        msg=f"'{key}' is not on the blackboard",
                        hint=suggest(key, keys) or f"available: {keys[:15]}",
                    )
                )
    if not errors:
        deps = {d.id: set(d.depends_on) | {k[1:] for k in d.inputs if k.startswith("@")} for d in plan.delegations}
        state: dict[str, int] = {}

        def visit(n: str, trail: tuple[str, ...]) -> None:
            if state.get(n) == 1:
                errors.append(ErrorDetail(loc=("delegations",), type="cycle", msg=" -> ".join(trail + (n,))))
                return
            if state.get(n) == 2:
                return
            state[n] = 1
            for m in sorted(deps[n]):
                visit(m, trail + (n,))
            state[n] = 2

        for n in ids:
            visit(n, ())
    return errors


class SupervisorAgent(BaseAgent):
    accepts_sub_agents = True

    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult:
        strategy = "sequential" if self.spec.backend == "rules" else self.spec.strategy
        if strategy == "sequential":
            children, plan_note = self._sequential(task, ctx, path, depth), "sequential"
        else:
            plan = self._route(task, ctx, path)
            children, plan_note = self._execute(plan, task, ctx, path, depth), plan.rationale
        return self._finish(task, ctx, path, children, plan_note)

    # ---------------------------------------------------------------- strategies
    def _sequential(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> list[AgentResult]:
        results: list[AgentResult] = []
        base = list(task.inputs or self.spec.inputs or ctx.input_keys)
        carried: list[str] = []  # main outputs of earlier siblings, passed forward
        for name in self.spec.sub_agents:
            child = self.children[name]
            if ctx.budget.exhausted:
                ctx.event(f"{path}/{name}", "skip", "budget exhausted")
                results.append(
                    child.result(f"{path}/{name}", "skipped", summary=f"budget exhausted ({ctx.budget.exhausted})")
                )
                continue
            ctx.budget.charge_delegation(path)
            ctx.event(path, "delegate", name)
            own = list(child.spec.inputs or base)
            res = child.run(
                AgentTask(instruction=task.instruction, inputs=own + [k for k in carried if k not in own]),
                ctx,
                path,
                depth + 1,
            )
            results.append(res)
            if res.status in ("ok", "partial") and res.artifacts:
                carried.append(res.artifacts[0])
        return results

    def _route(self, task: AgentTask, ctx: RunContext, path: str) -> DelegationPlan:
        team = json.dumps([c.card() for c in self.children.values()], ensure_ascii=False, indent=1)
        keys = sorted(ctx.blackboard)
        system = (
            self.system_prompt()
            + "\n\n"
            + ROUTER_RULES.format(team=team, keys=keys, max_delegations=self.spec.max_delegations)
        )
        user = f"Task: {task.instruction}"
        mem = self.memory_context(ctx, path)
        if mem:
            user += f"\n\nPrevious runs of this team:\n{mem}"

        def parse(data: Any) -> DelegationPlan:
            try:
                plan = DelegationPlan.model_validate(data)
            except ValidationError as exc:
                raise DelegationError("Delegation plan does not match the schema", details_from_pydantic(exc)) from exc
            errs = delegation_errors(plan, sorted(self.children), keys, self.spec.max_delegations)
            if errs:
                raise DelegationError(f"Delegation plan has {len(errs)} problem(s)", errs)
            return plan

        return structured_completion(
            self.llm(ctx, path),
            system,
            user,
            parse,
            model=self.model,
            max_attempts=self.settings.max_correction_attempts,
            json_mode=self.settings.json_mode,
            temperature=self.settings.temperature,
        ).value

    def _execute(
        self, plan: DelegationPlan, task: AgentTask, ctx: RunContext, path: str, depth: int
    ) -> list[AgentResult]:
        by_id = {d.id: d for d in plan.delegations}
        deps = {d.id: set(d.depends_on) | {k[1:] for k in d.inputs if k.startswith("@")} for d in plan.delegations}
        done: dict[str, AgentResult] = {}
        order: list[str] = []

        def visit(n: str) -> None:
            if n not in order:
                for m in sorted(deps[n]):
                    visit(m)
                order.append(n)

        for d in plan.delegations:
            visit(d.id)
        for did in order:
            d = by_id[did]
            child = self.children[d.agent]
            child_path = f"{path}/{d.agent}"
            blocked = sorted(x for x in deps[did] if done[x].status in ("failed", "skipped"))
            budget_hit = ctx.budget.exhausted is not None
            if blocked or budget_hit:
                why = "budget exhausted" if budget_hit else f"depends on failed delegation(s) {blocked}"
                ctx.event(child_path, "skip", why)
                done[did] = child.result(child_path, "skipped", summary=why)
                continue
            try:
                ctx.budget.charge_delegation(path)
            except FabricError as exc:
                done[did] = child.result(child_path, "skipped", summary=exc.message, error=exc.report)
                continue
            inputs = [
                done[k[1:]].artifacts[0] if k.startswith("@") and done[k[1:]].artifacts else k
                for k in d.inputs
                if not (k.startswith("@") and not done[k[1:]].artifacts)
            ]
            ctx.event(path, "delegate", f"{d.id} -> {d.agent}")
            done[did] = child.run(AgentTask(instruction=d.instruction, inputs=inputs), ctx, path, depth + 1)
        return [done[d.id] for d in plan.delegations]

    # ---------------------------------------------------------------- synthesis
    def _finish(
        self, task: AgentTask, ctx: RunContext, path: str, children: list[AgentResult], note: str
    ) -> AgentResult:
        ok = [c for c in children if c.status in ("ok", "partial")]
        status = (
            "ok"
            if len(ok) == len(children) and all(c.status == "ok" for c in children)
            else ("partial" if ok else "failed")
        )
        digest = {
            c.path: {
                "status": c.status,
                "summary": c.summary,
                "output": c.output,
                **({"error": c.error.message} if c.error else {}),
            }
            for c in children
        }
        output: dict[str, Any] = {
            "strategy": self.spec.strategy if self.spec.backend != "rules" else "sequential",
            "rationale": note,
            "delegations": {c.path: c.status for c in children},
        }
        summary = " | ".join(c.summary for c in ok)[:300] or "no sub-agent succeeded"
        if ctx.budget.exhausted:
            notes = [f"synthesis skipped: budget exhausted ({ctx.budget.exhausted})"]
        elif self.spec.synthesize and ok and self.spec.backend != "rules":
            user = f"Task: {task.instruction}\n\nSub-agent results:\n{compact(digest, max_chars=8000)}"
            notes: list[str] = []
            try:
                answer = _structured_or_text(
                    self, ctx, path, f"{self.system_prompt()}\n\n{SYNTHESIS_RULES}", user, [digest, task.instruction]
                )
                output["answer"] = answer
                summary = _summary_of(answer)
            except FabricError as exc:  # keep the children's work even if synthesis fails
                ctx.event(path, "error", f"synthesis: {exc.message}")
                notes.append(f"synthesis failed ({exc.category.value}): {exc.message}")
                status = "partial"
        else:
            notes = []
        error = None
        if status != "ok":
            failed = [c for c in children if c.status in ("failed", "skipped")]
            partial = [c for c in children if c.status == "partial"]
            message = (
                f"{len(failed)} sub-agent(s) did not succeed"
                if failed
                else f"{len(partial)} sub-agent(s) partially succeeded"
                if partial
                else "; ".join(notes) or "incomplete"
            )
            error = ErrorReport(
                category="dependency",
                message=message,
                details=[
                    ErrorDetail(loc=("sub_agents", c.agent), type=c.status, msg=c.summary[:200])
                    for c in failed + partial
                ],
            )
        return self.result(
            path,
            status,
            output=output,
            summary=summary,
            children=children,
            artifacts=[ctx.put(path, output)],
            error=error,
            notes=notes,
        )


class PydanticAISupervisor(SupervisorAgent):
    """Delegation through PydanticAI tool calls: the model calls ``delegate(agent, instruction, inputs)``."""

    def _run(self, task: AgentTask, ctx: RunContext, path: str, depth: int) -> AgentResult:
        from pydantic_ai import Agent, ModelRetry

        children_results: list[AgentResult] = []
        names = sorted(self.children)
        team = json.dumps([c.card() for c in self.children.values()], ensure_ascii=False)
        instructions = (
            f"{self.system_prompt()}\n\nDelegate work with the `delegate` tool. Sub-agents: {team}\n"
            f"Blackboard keys: {sorted(ctx.blackboard)}\n{SYNTHESIS_RULES}"
        )
        agent = Agent(
            self.fabric.pydantic_ai_model(self.spec),
            instructions=instructions,
            retries=self.settings.max_correction_attempts,
        )

        @agent.tool_plain
        def delegate(agent_name: str, instruction: str, inputs: list[str] | None = None) -> str:
            """Run one sub-agent and return its status and summary."""
            if agent_name not in self.children:
                raise ModelRetry(f"unknown agent '{agent_name}'; {suggest(agent_name, names) or f'use one of {names}'}")
            bad = [k for k in inputs or [] if k not in ctx.blackboard]
            if bad:
                raise ModelRetry(f"unknown blackboard keys {bad}; available: {sorted(ctx.blackboard)[:15]}")
            ctx.budget.charge_delegation(path)
            ctx.event(path, "delegate", agent_name)
            res = self.children[agent_name].run(
                AgentTask(instruction=instruction, inputs=inputs or []), ctx, path, depth + 1
            )
            children_results.append(res)
            return f"[{res.status}] {res.summary}\noutput: {compact(res.output, max_chars=3000)}"

        run = agent.run_sync(f"Task: {task.instruction}")
        usage = run.usage() if callable(run.usage) else run.usage
        n = usage.requests
        ctx.budget.charge_llm(path, n)
        ctx.llm_calls_by_path[path] = ctx.llm_calls_by_path.get(path, 0) + n
        answer = {"text": str(run.output)}
        ok = [c for c in children_results if c.status in ("ok", "partial")]
        status = "ok" if children_results and len(ok) == len(children_results) else ("partial" if ok else "failed")
        output = {
            "strategy": "pydantic_ai_tools",
            "delegations": {c.path: c.status for c in children_results},
            "answer": answer,
        }
        return self.result(
            path,
            status,
            output=output,
            summary=answer["text"][:300],
            children=children_results,
            artifacts=[ctx.put(path, output)],
        )
