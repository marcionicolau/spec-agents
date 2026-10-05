"""Generic component base class (template method).

    execute = parse params -> validate inputs against port types/constraints
              -> compute -> validate Result -> capture library warnings

Subclasses implement ``compute`` and, optionally, ``extra_checks`` (runtime),
``extra_static`` (plan time) and ``summarize`` (rule-based interpretation).
"""

from __future__ import annotations

import math
import warnings
from abc import ABC, abstractmethod
from typing import Annotated, Any, ClassVar

import numpy as np
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from .artifacts import TypeRegistry
from .errors import (
    ComponentExecutionError,
    DataValidationError,
    ErrorDetail,
    FabricError,
    ParamsValidationError,
    SpecError,
    details_from_pydantic,
)
from .spec import RESULT_PORT, ComponentSpec


def _finite(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


Num = Annotated[float | None, BeforeValidator(_finite)]
"""Float that serialises NaN/inf as ``None`` so results are always valid JSON."""


class ComponentParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ComponentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warnings: list[str] = Field(default_factory=list, description="assumption checks / caveats")


class ArtifactStore:
    """Blackboard of a pipeline run. Keys: '$inputs.<name>', '<step>.<port>'."""

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})

    def put(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``, replacing a previous value."""
        self._data[key] = value

    def get(self, key: str) -> Any:
        """The value stored under ``key`` (keys are ``<step_id>.<port>``, or ``$inputs.<name>`` for pipeline inputs); ``KeyError`` if absent."""
        return self._data[key]

    def has(self, key: str) -> bool:
        """Whether a value is stored under ``key``."""
        return key in self._data

    def keys(self) -> list[str]:
        """All keys, in insertion order."""
        return list(self._data)


class StepContext:
    """What a component can see and do while it executes one pipeline step.

    ``emit(name, value)`` stores a declared extra output in the `ArtifactStore` (undeclared names or wrong types raise a `SpecError`).
    ``llm``, ``llm_settings`` and ``objective`` are provided for ``runtime: prompt`` components (``llm`` is ``None`` when the run has no
    backend); ``on_step`` is propagated to nested pipelines.
    """

    def __init__(
        self,
        store: ArtifactStore,
        step_id: str,
        spec: ComponentSpec,
        types: TypeRegistry,
        depth: int = 0,
        *,
        llm: Any = None,
        llm_settings: Any = None,
        objective: str = "",
        on_step: Any = None,
    ) -> None:
        self.store, self.step_id, self.spec, self.types, self.depth = store, step_id, spec, types, depth
        self.llm = llm  # LLMBackend for 'runtime: prompt' components (None = unavailable)
        self.llm_settings = llm_settings  # LLMSettings of the calling agent/run
        self.objective = objective  # PipelinePlan.objective, for prompt templates
        self.on_step = on_step  # propagated to nested pipelines

    def emit(self, name: str, value: Any) -> None:
        """Store a declared extra output of the component as ``<step_id>.<name>``.

        Raises a `SpecError` for an output that is not declared in the spec (``undeclared_output``) or whose value does not match the declared artifact type
        (``output_type_mismatch``).
        """
        port = self.spec.outputs.get(name)
        if port is None:
            raise SpecError(
                f"Component '{self.spec.name}' emitted undeclared output '{name}'",
                [
                    ErrorDetail(
                        loc=("spec", "outputs"),
                        type="undeclared_output",
                        msg=f"'{name}' is not listed in outputs",
                        hint="declare it in the spec",
                    )
                ],
            )
        t = self.types.get(port.type)
        if not t.accepts(value):
            raise SpecError(
                f"Output '{name}' of '{self.spec.name}' is not of type '{port.type}'",
                [ErrorDetail(loc=("outputs", name), type="output_type_mismatch", msg=f"got {type(value).__name__}")],
            )
        self.store.put(f"{self.step_id}.{name}", value)


class Component[P: ComponentParams, R: ComponentResult](ABC):
    spec_name: ClassVar[str]
    Params: ClassVar[type[ComponentParams]]
    Result: ClassVar[type[ComponentResult]]

    def __init__(self, spec: ComponentSpec, types: TypeRegistry) -> None:
        self.spec, self.types = spec, types
        self.port_constraints: dict[str, BaseModel] = {}
        for port, ps in spec.inputs.items():
            self.port_constraints[port] = types.get(ps.type).parse_constraints(
                ps.constraints, ("inputs", port, "constraints")
            )
        for ps in spec.outputs.values():
            types.get(ps.type)

    # ------------------------------------------------------------------ hooks
    @abstractmethod
    def compute(self, inputs: dict[str, Any], params: P, ctx: StepContext) -> R:
        """Compute the result from validated inputs and parameters (the only place results are produced).

        Subclasses implement this. Return the component's `ComponentResult`; store declared extra outputs with ``ctx.emit(name, value)``. Do not call it
        directly: `execute` validates around it. Raise a `FabricError` subclass for failures a caller can act on.
        """
        ...

    def extra_checks(self, inputs: dict[str, Any], params: P) -> list[ErrorDetail]:
        """Runtime checks beyond port constraints. Return errors, don't raise."""
        return []

    def extra_static(self, bound: dict[str, BaseModel | None], params: P) -> list[ErrorDetail]:
        """Plan-time checks. ``bound`` maps each bound input port to its profile (None = unknown yet)."""
        return []

    def summarize(self, result: dict[str, Any], /) -> tuple[str, list[str]] | None:
        """Optional deterministic (headline, findings) for rule-based interpretation."""
        return None

    # ------------------------------------------------------------------ params
    def parse_params(self, raw: dict[str, Any] | None) -> P:
        """Validate raw parameters (``None`` = defaults) into the component's ``Params`` model; raises `ParamsValidationError` located under ``params``."""
        try:
            return self.Params.model_validate(raw or {})  # ty: ignore[invalid-return-type]
        except ValidationError as exc:
            raise ParamsValidationError(
                f"Invalid parameters for '{self.spec.name}'",
                details_from_pydantic(exc, ("params",)),
                component=self.spec.name,
            ) from exc

    # ------------------------------------------------------------------ validation
    def static_checks(self, bound: dict[str, BaseModel | None], params: P) -> list[ErrorDetail]:
        """Plan-time checks from the profiles of the bound inputs; returns every problem found.

        Reports required ports that are not bound (``port_unbound``), applies each artifact type's static checks to the profile, and adds `extra_static`.
        ``bound`` maps each bound port to its profile, or ``None`` when the profile is not known yet.
        """
        errors: list[ErrorDetail] = []
        for port, ps in self.spec.inputs.items():
            if port not in bound:
                if ps.required:
                    errors.append(
                        ErrorDetail(
                            loc=("inputs", port),
                            type="port_unbound",
                            msg=f"required input '{port}' ({ps.type}) is not bound",
                            hint="bind it to '$inputs.<name>' or '<step_id>.<output>'",
                        )
                    )
                continue
            profile = bound[port]
            if profile is not None:
                errors += self.types.get(ps.type).static_check(
                    profile, self.port_constraints[port], params, ("inputs", port)
                )
        return errors + self.extra_static(bound, params)

    def validate_inputs(self, inputs: dict[str, Any], params: P) -> None:
        """Check the runtime inputs before `compute`; raises `DataValidationError` listing every problem.

        Order: artifact types (``wrong_artifact_type``), then static checks on the profiles, then the types' runtime checks on the real values, then `extra_checks`;
        later stages run only when the earlier ones found nothing.
        """
        errors: list[ErrorDetail] = []
        bound: dict[str, BaseModel | None] = {}
        for port, ps in self.spec.inputs.items():
            if port not in inputs or inputs[port] is None:
                continue
            t = self.types.get(ps.type)
            if not t.accepts(inputs[port]):
                errors.append(
                    ErrorDetail(
                        loc=("inputs", port),
                        type="wrong_artifact_type",
                        msg=f"expected {ps.type}, got {type(inputs[port]).__name__}",
                    )
                )
                continue
            bound[port] = t.profile(inputs[port])
        if not errors:
            errors = self.static_checks(bound, params)
        if not errors:
            for port in bound:
                errors += self.types.get(self.spec.inputs[port].type).runtime_check(
                    inputs[port], self.port_constraints[port], params, ("inputs", port)
                )
        if not errors:
            errors = self.extra_checks(inputs, params)
        if errors:
            raise DataValidationError(
                f"Inputs do not satisfy '{self.spec.name}' requirements", errors, component=self.spec.name
            )

    # ------------------------------------------------------------------ template method
    def execute(self, inputs: dict[str, Any], raw_params: dict[str, Any] | None, ctx: StepContext) -> R:
        """Run the component: the template method every step goes through.

        Parses the parameters (`ParamsValidationError`), validates the inputs (types, static and runtime port constraints, ``extra_checks``;
        `DataValidationError` with every problem), calls `compute`, re-validates the result against the ``Result`` model, adds non-deprecation library
        warnings as ``[library] ...`` result warnings and stores the JSON result under ``<step_id>.result``. Any `FabricError` is re-raised with the component
        and step id attached.
        """
        try:
            params = self.parse_params(raw_params)
            self.validate_inputs(inputs, params)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = self.compute(inputs, params, ctx)
            lib = sorted(
                {
                    str(w.message).split("\n")[0][:160]
                    for w in caught
                    if not issubclass(w.category, (DeprecationWarning, FutureWarning, PendingDeprecationWarning))
                }
            )
            result = self.Result.model_validate(result.model_dump())
            result.warnings.extend(f"[library] {m}" for m in lib)
            ctx.store.put(f"{ctx.step_id}.{RESULT_PORT}", result.model_dump(mode="json"))
            return result  # ty: ignore[invalid-return-type]
        except FabricError as exc:
            raise exc.with_context(component=self.spec.name, step_id=ctx.step_id) from None
        except ValidationError as exc:
            raise SpecError(
                f"'{self.spec.name}' produced a result that violates its Result model",
                details_from_pydantic(exc, ("result",)),
                component=self.spec.name,
                step_id=ctx.step_id,
            ) from exc
        except Exception as exc:  # library / numerical failures
            raise wrap_execution_error(exc, self.spec.name, ctx.step_id) from exc


_KNOWN_HINTS: list[tuple[str, str, bool]] = [
    ("singular matrix", "inputs are perfectly collinear; remove redundant columns", True),
    ("perfect separation", "a predictor perfectly separates the outcome", True),
    ("must have at least", "not enough observations for this configuration", True),
    ("n_samples", "not enough rows for the requested number of clusters/components", True),
    ("could not convert", "a column contains non-numeric values", True),
]


def wrap_execution_error(exc: Exception, component: str, step_id: str) -> ComponentExecutionError:
    text = f"{type(exc).__name__}: {exc}".lower()
    hint, recoverable = None, False
    for needle, h, rec in _KNOWN_HINTS:
        if needle in text:
            hint, recoverable = h, rec
            break
    return ComponentExecutionError(
        f"'{component}' failed during computation",
        [ErrorDetail(type=type(exc).__name__, msg=str(exc)[:300], hint=hint)],
        component=component,
        step_id=step_id,
        recoverable=recoverable,
    )


__all__ = [
    "ArtifactStore",
    "Component",
    "ComponentParams",
    "ComponentResult",
    "Num",
    "StepContext",
]
