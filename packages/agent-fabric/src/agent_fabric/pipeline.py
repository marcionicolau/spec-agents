"""Pipelines: typed DAGs of components wired through ports.

References (values of ``step.inputs`` and ``plan.outputs``):
    ``$inputs.<name>``   a pipeline input
    ``<step_id>.<port>`` an output of an upstream step (``result`` = its JSON Result)
    ``$params.<name>``   only inside PipelineSpec templates (substituted on instantiation)

Auto-binding (keeps LLM plans short): an unbound input port binds to the pipeline input
with the same name; a *required* unbound port binds to the only type-compatible input.

Validation layers, all producing located ``ErrorDetail``s:
1. structure (pydantic): ids, refs syntax, dependencies, cycles
2. semantics (registry): components, params, port names, reference targets, type compatibility
3. static data (profiles): port constraints checked on input profiles before execution
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator, model_validator

from .artifacts import TypeRegistry
from .component import Component, ComponentParams, ComponentResult, StepContext
from .errors import (
    ComponentExecutionError,
    DataValidationError,
    ErrorDetail,
    FabricError,
    PlanValidationError,
    SpecError,
    details_from_pydantic,
    suggest,
)
from .spec import RESULT_PORT, ComponentSpec, ParamDoc, PipelineSpec, PortSpec

MAX_STEPS = 20
MAX_NESTING = 8
REF_RE = re.compile(r"^(\$inputs|\$params|[a-z][a-z0-9_]*)\.[a-z][a-z0-9_]*$")


def types_compatible(src: str, dst: str) -> bool:
    """Whether an artifact of type ``src`` can feed a port of type ``dst`` (equal types, or either side ``any``)."""
    return dst == "any" or src == "any" or src == dst


# ============================================================================ plan models


class PipelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="unique snake_case id")
    component: str
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict, description="port -> reference")
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("inputs")
    @classmethod
    def _refs(cls, v: dict[str, str]) -> dict[str, str]:
        # Small models often emit "$steps.<id>.<port>" by analogy with "$inputs." — an
        # unambiguous typo, so it is normalized instead of burning a correction attempt.
        v = {p: r.removeprefix("$steps.") if isinstance(r, str) else r for p, r in v.items()}
        bad = {p: r for p, r in v.items() if not isinstance(r, str) or not REF_RE.match(r)}
        if bad:
            raise ValueError(f"invalid references {bad}; use '$inputs.<name>' or '<step_id>.<port>'")
        return v

    def step_refs(self) -> set[str]:
        """Ids of the steps referenced by this step's inputs (``<step>.<port>``; ``$inputs`` and ``$params`` references are not step references)."""
        return {r.split(".")[0] for r in self.inputs.values() if not r.startswith("$")}


class PipelinePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=3)
    steps: list[PipelineStep] = Field(min_length=1, max_length=MAX_STEPS)
    outputs: dict[str, str] = Field(default_factory=dict, description="exposed name -> '<step_id>.<port>'")

    @model_validator(mode="after")
    def _dag(self) -> PipelinePlan:
        ids = [s.id for s in self.steps]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate step ids: {dupes}")
        for s in self.steps:
            unknown = sorted((set(s.depends_on) | s.step_refs()) - set(ids))
            if unknown:
                raise ValueError(f"step '{s.id}' references unknown steps {unknown}")
            if s.id in self.all_deps(s):
                raise ValueError(f"step '{s.id}' depends on itself")
        self.outputs = {n: r.removeprefix("$steps.") for n, r in self.outputs.items()}
        for name, ref in self.outputs.items():
            if not REF_RE.match(ref) or ref.startswith("$") or ref.split(".")[0] not in ids:
                raise ValueError(f"output '{name}' must reference '<step_id>.<port>' of an existing step, got {ref!r}")
        self.topological_order()
        return self

    def all_deps(self, step: PipelineStep) -> set[str]:
        """Ids of all steps this step depends on: explicit ``depends_on`` plus the steps its inputs reference."""
        return set(step.depends_on) | step.step_refs()

    def topological_order(self) -> list[PipelineStep]:
        """Steps ordered so every step follows its dependencies; raises ``ValueError`` naming the cycle if there is one."""
        by_id = {s.id: s for s in self.steps}
        order: list[PipelineStep] = []
        state: dict[str, int] = {}

        def visit(sid: str, path: tuple[str, ...]) -> None:
            if state.get(sid) == 2:
                return
            if state.get(sid) == 1:
                raise ValueError(f"dependency cycle: {' -> '.join(path + (sid,))}")
            state[sid] = 1
            for dep in sorted(self.all_deps(by_id[sid])):
                visit(dep, path + (sid,))
            state[sid] = 2
            order.append(by_id[sid])

        for s in self.steps:
            visit(s.id, ())
        return order


# ============================================================================ inputs


class PipelineInputs:
    """Declared pipeline inputs + (optionally) their values and profiles."""

    def __init__(self, specs: dict[str, PortSpec], values: dict[str, Any] | None, types: TypeRegistry) -> None:
        self.specs, self.values, self.types = dict(specs), dict(values or {}), types
        self.profiles: dict[str, BaseModel | None] = {}
        for name, spec in self.specs.items():
            v = self.values.get(name)
            self.profiles[name] = types.get(spec.type).profile(v) if v is not None else None

    @classmethod
    def from_values(cls, values: dict[str, Any], types: TypeRegistry) -> PipelineInputs:
        """Build inputs from raw values: each artifact type is inferred from the value and profiled."""
        return cls({k: PortSpec(type=types.infer(v).name) for k, v in values.items()}, values, types)

    def to_prompt(self) -> str:
        """Describe the inputs for a planner prompt: ``$inputs.<name> (<type>)`` followed by the profile (or value preview) of each."""
        lines = []
        for name, spec in self.specs.items():
            prof = self.profiles.get(name)
            desc = (
                self.types.get(spec.type).describe(prof, self.values.get(name))
                if (prof or name in self.values)
                else spec.type
            )
            lines.append(f"$inputs.{name} ({spec.type}){': ' + spec.description if spec.description else ''}\n{desc}")
        return "\n".join(lines) or "(no inputs)"


def resolve_bindings(step: PipelineStep, comp: Component, inputs: PipelineInputs | None) -> dict[str, str]:
    """Return the final ``port -> reference`` bindings of a step.

    Explicit bindings win; unbound ports auto-bind to a same-named pipeline input or, for a required port, to the only type-compatible input.
    """
    bindings = dict(step.inputs)
    if inputs is None:
        return bindings
    for port, ps in comp.spec.inputs.items():
        if port in bindings:
            continue
        if port in inputs.specs:
            bindings[port] = f"$inputs.{port}"
        elif ps.required:
            cands = [n for n, s in inputs.specs.items() if types_compatible(s.type, ps.type)]
            if len(cands) == 1:
                bindings[port] = f"$inputs.{cands[0]}"
    return bindings


def _output_type(registry: Any, component: str, port: str) -> str | None:
    if port == RESULT_PORT:
        return "json"
    out = registry.spec(component).outputs.get(port)
    return out.type if out else None


def _has_param_ref(v: Any) -> bool:
    if isinstance(v, str):
        return v.startswith("$params.")
    if isinstance(v, dict):
        return any(_has_param_ref(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_param_ref(x) for x in v)
    return False


def _param_ref_errors(
    params: dict[str, Any], ids: set[str], loc: tuple[str | int, ...], allow_param_refs: bool
) -> list[ErrorDetail]:
    """Flag step references used as literal param values (e.g. ``"focus_files": ["pick.context"]``).

    Params are literals: a string matching ``<step_id>.<port>`` or ``$steps.<id>.<port>`` — or
    ``$inputs.<name>`` anywhere, or ``$params.<name>`` outside pipeline templates — is a misplaced
    reference, not a value.
    """
    errors: list[ErrorDetail] = []

    def walk(v: Any, ploc: tuple[str | int, ...]) -> None:
        if isinstance(v, str):
            if v.startswith("$steps."):
                misplaced = True
            elif (m := REF_RE.match(v)) is not None:
                head = m.group(1)
                misplaced = head == "$inputs" or head in ids or (head == "$params" and not allow_param_refs)
            else:
                misplaced = False
            if misplaced:
                errors.append(
                    ErrorDetail(
                        loc=ploc,
                        type="ref_in_param",
                        input=v,
                        msg=f"'{v}' is a reference used as a literal param value",
                        hint="params take literal values; bind step outputs through this step's 'inputs'",
                    )
                )
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, ploc + (k,))
        elif isinstance(v, list):
            for j, x in enumerate(v):
                walk(x, ploc + (j,))

    for k, v in params.items():
        walk(v, loc + ("params", k))
    return errors


def semantic_errors(
    plan: PipelinePlan, registry: Any, inputs: PipelineInputs | None, allow_param_refs: bool = False
) -> list[ErrorDetail]:
    """Check a parsed plan against the registry and the input profiles; returns every problem found.

    Covers unknown components, unbound or mistyped ports, bad references, unknown params and static constraints. With ``allow_param_refs``
    ``$params.*`` references are accepted (pipeline templates).
    """
    errors: list[ErrorDetail] = []
    by_id = {s.id: s for s in plan.steps}
    for i, step in enumerate(plan.steps):
        loc = ("steps", i)
        if not registry.has(step.component):
            errors.append(
                ErrorDetail(
                    loc=loc + ("component",),
                    type="unknown_component",
                    input=step.component,
                    msg=f"component '{step.component}' does not exist",
                    hint=suggest(step.component, registry.names()) or f"use one of {registry.names()}",
                )
            )
            continue
        comp = registry.get(step.component)
        # ---- params
        params = None
        if allow_param_refs and _has_param_ref(step.params):
            extra = [k for k in step.params if k not in comp.Params.model_fields]
            errors += [
                ErrorDetail(
                    loc=loc + ("params", k),
                    type="extra_forbidden",
                    msg="unknown parameter",
                    hint=suggest(k, comp.Params.model_fields),
                )
                for k in extra
            ]
        else:
            try:
                params = comp.Params.model_validate(step.params)
            except ValidationError as exc:
                errors += details_from_pydantic(exc, loc + ("params",))
        errors += _param_ref_errors(step.params, set(by_id), loc, allow_param_refs)
        # ---- ports
        for port in step.inputs:
            if port not in comp.spec.inputs:
                errors.append(
                    ErrorDetail(
                        loc=loc + ("inputs", port),
                        type="unknown_port",
                        input=port,
                        msg=f"'{step.component}' has no input port '{port}'",
                        hint=suggest(port, comp.spec.inputs) or f"ports: {sorted(comp.spec.inputs)}",
                    )
                )
        bindings = resolve_bindings(step, comp, inputs)
        bound: dict[str, BaseModel | None] = {}
        for port, ref in bindings.items():
            if port not in comp.spec.inputs:
                continue
            want = comp.spec.inputs[port].type
            head, name = ref.split(".", 1)
            ploc = loc + ("inputs", port)
            if head == "$params":
                errors.append(
                    ErrorDetail(
                        loc=ploc,
                        type="param_ref_not_allowed",
                        msg="$params references are only valid in pipeline specs",
                    )
                )
                continue
            if head == "$inputs":
                if inputs is None:
                    bound[port] = None
                    continue
                if name not in inputs.specs:
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="unknown_input",
                            input=ref,
                            msg=f"pipeline has no input '{name}'",
                            hint=suggest(name, inputs.specs) or f"inputs: {sorted(inputs.specs)}",
                        )
                    )
                    bound[port] = None  # treat as bound: avoid cascading 'unbound' errors
                    continue
                have = inputs.specs[name].type
                bound[port] = inputs.profiles.get(name) if types_compatible(have, want) else None
            else:
                producer = by_id[head]
                if not registry.has(producer.component):
                    continue  # already reported
                have = _output_type(registry, producer.component, name)
                if have is None:
                    outs = [RESULT_PORT, *registry.spec(producer.component).outputs]
                    errors.append(
                        ErrorDetail(
                            loc=ploc,
                            type="unknown_output",
                            input=ref,
                            msg=f"step '{head}' ({producer.component}) has no output '{name}'",
                            hint=suggest(name, outs) or f"outputs: {outs}",
                        )
                    )
                    bound[port] = None
                    continue
                bound[port] = None
            if not types_compatible(have, want):
                errors.append(
                    ErrorDetail(
                        loc=ploc,
                        type="type_mismatch",
                        input=ref,
                        msg=f"'{ref}' is {have}, port '{port}' expects {want}",
                    )
                )
        if params is not None and inputs is not None:
            for d in comp.static_checks(bound, params):
                errors.append(d.model_copy(update={"loc": loc + d.loc}))
    for name, ref in plan.outputs.items():
        head, port = ref.split(".", 1)
        comp_name = by_id[head].component
        if registry.has(comp_name) and _output_type(registry, comp_name, port) is None:
            errors.append(
                ErrorDetail(
                    loc=("outputs", name), type="unknown_output", input=ref, msg=f"step '{head}' has no output '{port}'"
                )
            )
    return errors


def parse_plan(
    raw: dict[str, Any] | PipelinePlan,
    registry: Any,
    inputs: PipelineInputs | None = None,
    allow_param_refs: bool = False,
) -> PipelinePlan:
    """Validate a raw plan end-to-end; raises ``PlanValidationError`` listing every problem."""
    if isinstance(raw, PipelinePlan):
        plan = raw
    else:
        try:
            plan = PipelinePlan.model_validate(raw)
        except ValidationError as exc:
            raise PlanValidationError("Pipeline plan is structurally invalid", details_from_pydantic(exc)) from exc
    errors = semantic_errors(plan, registry, inputs, allow_param_refs)
    if errors:
        raise PlanValidationError(f"Pipeline plan has {len(errors)} problem(s)", errors)
    return plan


def validate_pipeline_spec(pspec: PipelineSpec, registry: Any) -> None:
    """Validate a `PipelineSpec` against the registry at registration time; raises a `SpecError` with every problem found."""
    raw = {"objective": pspec.title, "steps": [s.model_dump() for s in pspec.steps], "outputs": pspec.outputs}
    try:
        parse_plan(raw, registry, PipelineInputs(pspec.inputs, None, registry.types), allow_param_refs=True)
    except PlanValidationError as exc:
        raise SpecError(f"Pipeline spec '{pspec.name}' is invalid", exc.details, component=pspec.name) from exc


# ============================================================================ pipelines as components


class PipelineResult(ComponentResult):
    pipeline: str
    steps: dict[str, str]
    step_results: dict[str, Any]


class PipelineComponent(Component[ComponentParams, PipelineResult]):
    """Composite: a registered PipelineSpec exposed as a component (pipelines nest)."""

    Result = PipelineResult
    pspec: PipelineSpec
    registry: Any

    @classmethod
    def from_spec(cls, pspec: PipelineSpec, registry: Any) -> PipelineComponent:
        """Build the component class for a `PipelineSpec` and return an instance (called at registration).

        Creates the params model from the spec's parameters, derives the output port types from the producing steps, and registers the pipeline under
        the spec name, so pipelines can be used wherever components can.
        """
        fields = {k: (Any, ... if p.required else p.default) for k, p in pspec.params.items()}
        params_model = create_model(f"{pspec.name}_params", __base__=ComponentParams, **fields)  # ty: ignore[no-matching-overload]
        by_id = {s.id: s for s in pspec.steps}
        outputs = {}
        for name, ref in pspec.outputs.items():
            head, port = ref.split(".", 1)
            outputs[name] = PortSpec(type=_output_type(registry, by_id[head].component, port) or "any")
        cspec = ComponentSpec(
            name=pspec.name,
            version=pspec.version,
            title=pspec.title,
            description=pspec.description,
            domain=pspec.domain,
            category="pipeline",
            tags=pspec.tags,
            llm=pspec.llm,
            guidance=pspec.guidance,
            params={k: ParamDoc(description=p.description, example=p.example) for k, p in pspec.params.items()},
            inputs=pspec.inputs,
            outputs=outputs,
        )
        sub = type(
            f"Pipeline_{pspec.name}",
            (cls,),
            {"Params": params_model, "spec_name": pspec.name, "pspec": pspec, "registry": registry},
        )
        return sub(cspec, registry.types)

    def compute(self, inputs: dict[str, Any], params: ComponentParams, ctx: StepContext) -> PipelineResult:
        """Run the pipeline as one step of an outer pipeline.

        Instantiates the spec with the step's parameters, validates the plan against the bound inputs (inner errors are re-located as
        ``pipeline.<step_id>...``), executes it one nesting level deeper (at most ``MAX_NESTING``) with the caller's LLM backend and step callback,
        and emits the declared outputs. A failed inner step makes this step fail with the inner errors; the result lists each step's status and
        result and aggregates warnings.
        """
        from .executor import PipelineExecutor, StepStatus

        if ctx.depth >= MAX_NESTING:
            raise ComponentExecutionError(f"pipeline nesting deeper than {MAX_NESTING}")
        raw = self.pspec.instantiate(params.model_dump())
        pin = PipelineInputs(self.pspec.inputs, {k: v for k, v in inputs.items() if v is not None}, self.types)
        try:
            plan = parse_plan(raw, self.registry, pin)
        except PlanValidationError as exc:  # re-locate inner errors as pipeline.<step_id>...
            ids = [s["id"] for s in raw["steps"]]
            details = [
                d.model_copy(update={"loc": ("pipeline", ids[d.loc[1]]) + d.loc[2:]})
                if len(d.loc) > 1 and d.loc[0] == "steps" and isinstance(d.loc[1], int)
                else d
                for d in exc.details
            ]
            raise DataValidationError(f"pipeline '{self.pspec.name}' cannot run on these inputs", details) from exc
        report = PipelineExecutor(self.registry, llm=ctx.llm, llm_settings=ctx.llm_settings, on_step=ctx.on_step).run(
            plan, pin, depth=ctx.depth + 1
        )
        failed = [o for o in report.outcomes if o.status in (StepStatus.FAILED, StepStatus.SKIPPED)]
        if failed:
            details = [
                d.model_copy(update={"loc": ("pipeline", o.step_id) + d.loc})
                for o in failed
                if o.error
                for d in (o.error.details or [ErrorDetail(type="failed", msg=o.error.message)])
            ]
            raise ComponentExecutionError(
                f"pipeline '{self.pspec.name}': {len(failed)} step(s) did not succeed",
                details,
                recoverable=all(o.error and o.error.recoverable for o in failed if o.status == StepStatus.FAILED),
            )
        for name, ref in self.pspec.outputs.items():
            ctx.emit(name, report.artifacts.get(ref))
        warns = [f"{o.step_id}: {w}" for o in report.outcomes for w in (o.result or {}).get("warnings", [])]
        return PipelineResult(
            pipeline=self.pspec.name,
            steps={o.step_id: o.status.value for o in report.outcomes},
            step_results={o.step_id: o.result for o in report.outcomes},
            warnings=warns,
        )


__all__ = [
    "FabricError",
    "PipelineComponent",
    "PipelineInputs",
    "PipelinePlan",
    "PipelineStep",
    "parse_plan",
    "resolve_bindings",
    "semantic_errors",
    "types_compatible",
    "validate_pipeline_spec",
]
