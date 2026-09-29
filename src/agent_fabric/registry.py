"""Microkernel: registry of artifact types, components and pipelines, grouped by domain.

A *domain pack* (statistics, text, ...) is a spec directory + component classes
(+ optional pipeline specs, types and planner builders). Packs load with
``Registry.load_domain`` or through the entry-point group ``agent_fabric.domains``
(value: ``callable(registry) -> None``).
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Iterable

from .artifacts import TypeRegistry
from .errors import ErrorDetail, SpecError, suggest
from .spec import AnySpec, ComponentSpec, PipelineSpec, load_spec_dir

DOMAIN_ENTRY_POINT = "agent_fabric.domains"

_DECLARED: list[type] = []


def component[C: type](spec_name: str) -> Callable[[C], C]:
    """Class decorator binding an implementation to a spec name."""

    def deco(cls: C) -> C:
        cls.spec_name = spec_name  # type: ignore[attr-defined]
        if cls not in _DECLARED:
            _DECLARED.append(cls)
        return cls

    return deco


def declared_components() -> list[type]:
    return list(_DECLARED)


class Registry:
    def __init__(self, types: TypeRegistry | None = None) -> None:
        self.types = types or TypeRegistry()
        try:
            from .tabular import register_tabular_types
            register_tabular_types(self.types)
        except ImportError:  # pragma: no cover - pandas missing
            pass
        self._specs: dict[str, AnySpec] = {}
        self._components: dict[str, Any] = {}
        self._pipelines: dict[str, PipelineSpec] = {}

    # ------------------------------------------------------------ specs
    def add_specs(self, specs: Iterable[AnySpec]) -> None:
        for spec in specs:
            old = self._specs.get(spec.name)
            if old is not None and old != spec:
                raise SpecError(f"Spec '{spec.name}' defined twice with different content")
            self._specs[spec.name] = spec

    # ------------------------------------------------------------ components
    def register(self, cls: type) -> None:
        from .component import Component, ComponentParams, ComponentResult

        name = getattr(cls, "spec_name", None)
        if not (isinstance(cls, type) and issubclass(cls, Component)):
            raise SpecError(f"{cls!r} is not a Component subclass")
        spec = self._specs.get(str(name))
        if not isinstance(spec, ComponentSpec):
            raise SpecError(f"No component spec for class {cls.__name__} (spec_name={name!r})",
                            [ErrorDetail(type="spec_not_found", msg=f"'{name}' has no component YAML spec",
                                         hint=suggest(str(name), self._specs) or "add a YAML file to the domain's spec directory")])
        errors: list[ErrorDetail] = []
        pm, rm = getattr(cls, "Params", None), getattr(cls, "Result", None)
        if not (isinstance(pm, type) and issubclass(pm, ComponentParams)):
            errors.append(ErrorDetail(loc=("Params",), type="bad_model", msg="Params must subclass ComponentParams"))
        if not (isinstance(rm, type) and issubclass(rm, ComponentResult)):
            errors.append(ErrorDetail(loc=("Result",), type="bad_model", msg="Result must subclass ComponentResult"))
        if not errors:
            code, declared = set(pm.model_fields), set(spec.params)
            errors += [ErrorDetail(loc=("params", f), type="spec_only_param", msg="declared in the spec but missing in Params")
                       for f in sorted(declared - code)]
            errors += [ErrorDetail(loc=("params", f), type="undocumented_param", msg="present in Params but not documented in the spec")
                       for f in sorted(code - declared)]
        for port, ps in {**spec.inputs, **spec.outputs}.items():
            if not self.types.has(ps.type):
                errors.append(ErrorDetail(loc=("ports", port, "type"), type="unknown_type", input=ps.type,
                                          msg=f"artifact type '{ps.type}' is not registered",
                                          hint=suggest(ps.type, self.types.names()) or f"available: {self.types.names()}"))
        if errors:
            raise SpecError(f"Contract mismatch between spec '{name}' and {cls.__name__}", errors, component=name)
        self._components[spec.name] = cls(spec, self.types)  # parses port constraints (may raise SpecError)

    def register_pipeline(self, pspec: PipelineSpec) -> None:
        from .pipeline import PipelineComponent, validate_pipeline_spec

        validate_pipeline_spec(pspec, self)
        self._specs[pspec.name] = pspec
        self._pipelines[pspec.name] = pspec
        if pspec.expose_as_component:
            self._components[pspec.name] = PipelineComponent.from_spec(pspec, self)

    def load_domain(self, spec_dir: str | Path | None = None, classes: Iterable[type] | None = None,
                    specs: Iterable[AnySpec] | None = None) -> list[str]:
        """Load a domain pack: specs, then components, then pipelines (dependency order)."""
        loaded = list(specs or []) + (load_spec_dir(spec_dir) if spec_dir else [])
        self.add_specs(loaded)
        names = {s.name for s in loaded}
        for cls in classes if classes is not None else declared_components():
            if getattr(cls, "spec_name", None) in names and cls.spec_name not in self._components:
                self.register(cls)
        missing = [s.name for s in loaded if isinstance(s, ComponentSpec) and s.name not in self._components]
        if missing:
            raise SpecError(f"Component specs without implementation: {missing}",
                            [ErrorDetail(loc=("components", m), type="implementation_missing",
                                         msg="no @component class registered for this spec") for m in missing])
        pending = [s for s in loaded if isinstance(s, PipelineSpec)]
        while pending:
            ready = [p for p in pending if all(st.component in self._components for st in p.steps)]
            if not ready:  # report the first blocker precisely
                self.register_pipeline(pending[0])
            for p in ready:
                self.register_pipeline(p)
            pending = [p for p in pending if p not in ready]
        return sorted(names)

    def discover_domains(self) -> list[str]:
        found = []
        for ep in metadata.entry_points(group=DOMAIN_ENTRY_POINT):
            ep.load()(self)
            found.append(ep.name)
        return found

    # ------------------------------------------------------------ queries
    def get(self, name: str) -> Any:
        try:
            return self._components[name]
        except KeyError:
            raise SpecError(f"Unknown component '{name}'",
                            [ErrorDetail(type="unknown_component", msg=f"'{name}' is not registered", input=name,
                                         hint=suggest(name, self._components) or f"available: {self.names()}")]) from None

    def has(self, name: str) -> bool:
        return name in self._components and self._components[name].spec.enabled

    def names(self, domains: Iterable[str] | None = None) -> list[str]:
        doms = set(domains) if domains else None
        return sorted(n for n, c in self._components.items()
                      if c.spec.enabled and (doms is None or c.spec.domain in doms or c.spec.domain == "core"))

    def domains(self) -> list[str]:
        return sorted({c.spec.domain for c in self._components.values()})

    def spec(self, name: str) -> Any:
        return self.get(name).spec

    def pipeline(self, name: str) -> PipelineSpec:
        if name not in self._pipelines:
            raise SpecError(f"Unknown pipeline '{name}'",
                            [ErrorDetail(type="unknown_pipeline", msg=f"'{name}' is not registered", input=name,
                                         hint=suggest(name, self._pipelines) or f"available: {sorted(self._pipelines)}")])
        return self._pipelines[name]

    def guidance(self, name: str, section: str | None = None, max_chars: int | None = None) -> str:
        """Progressive disclosure: the full SKILL.md body (or one section) of a component, on demand."""
        g = self.spec(name).guidance
        return g.section(section, max_chars) if section else g.body

    def pipelines(self) -> list[str]:
        return sorted(self._pipelines)

    def catalog(self, domains: Iterable[str] | None = None, compact: bool = True) -> list[dict[str, Any]]:
        """Component catalogue for planner prompts (short, for small local models)."""
        out = []
        for name in self.names(domains):
            comp = self._components[name]
            spec = comp.spec
            schema = comp.Params.model_json_schema()
            params = {}
            for pname, prop in schema.get("properties", {}).items():
                t = prop.get("type") or [a.get("type") for a in prop.get("anyOf", []) if a.get("type") not in (None, "null")]
                if "enum" in prop:
                    t = f"one of {prop['enum']}"
                entry = {"type": t or "any", "required": pname in schema.get("required", []),
                         "doc": spec.params[pname].description}
                if not compact and "default" in prop:
                    entry["default"] = prop["default"]
                params[pname] = entry
            item: dict[str, Any] = {
                "name": name, "domain": spec.domain, "description": spec.description, "when_to_use": spec.when_to_use,
                "params": params,
                "inputs": {p: f"{ps.type}{'' if ps.required else ' (optional)'}" for p, ps in spec.inputs.items()},
                "outputs": {"result": "json", **{p: ps.type for p, ps in spec.outputs.items()}},
            }
            if spec.avoid_when:
                item["avoid_when"] = spec.avoid_when
            out.append(item)
        return out
