"""Microkernel: registry of artifact types, components and pipelines, grouped by domain.

A *domain pack* (statistics, text, ...) is a spec directory + component classes
(+ optional pipeline specs, types and planner builders). Packs load with
``Registry.load_domain`` or through the entry-point group ``agent_fabric.domains``
(value: ``callable(registry) -> None``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import metadata
from pathlib import Path
from typing import Any

from .artifacts import TypeRegistry
from .errors import ErrorDetail, SpecError, suggest
from .spec import AnySpec, ComponentSpec, PipelineSpec, load_spec_dir

DOMAIN_ENTRY_POINT = "agent_fabric.domains"

_DECLARED: list[type] = []


def component[C: type](spec_name: str) -> Callable[[C], C]:
    """Class decorator binding an implementation to a spec name."""

    def deco(cls: C) -> C:
        cls.spec_name = spec_name  # ty: ignore[unresolved-attribute]
        if cls not in _DECLARED:
            _DECLARED.append(cls)
        return cls

    return deco


def declared_components() -> list[type]:
    """Return every class decorated with `component` so far, in declaration order."""
    return list(_DECLARED)


class Registry:
    """Catalogue of artifact types, components, pipelines and domains.

    Domain packs register through ``load_domain(spec_dir, classes)``, which binds each ``SKILL.md`` contract to its implementation class
    (``runtime: prompt`` skills need no class); registration fails when spec and class disagree. Pipelines become components, so they nest.
    Query with ``get``, ``spec``, ``names``, ``pipelines`` and ``catalog`` (the compact list planners read).
    """

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
        self._loaded_dirs: dict[Path, list[str]] = {}

    # ------------------------------------------------------------ specs
    def add_specs(self, specs: Iterable[AnySpec]) -> None:
        """Add specs by name; raises a `SpecError` when a name is defined twice with different content (identical re-adds are ignored)."""
        for spec in specs:
            old = self._specs.get(spec.name)
            if old is not None and old != spec:
                raise SpecError(f"Spec '{spec.name}' defined twice with different content")
            self._specs[spec.name] = spec

    # ------------------------------------------------------------ components
    def register(self, cls: type) -> None:
        """Bind an implementation class to the spec that has its ``spec_name`` and register the component.

        Fails with a `SpecError` listing every mismatch: the class is not a `Component`, no spec exists for it, ``Params``/``Result`` have the wrong base classes,
        spec parameters and ``Params`` fields differ (``spec_only_param``, ``undocumented_param``), or a port uses an unregistered artifact type.
        """
        from .component import Component, ComponentParams, ComponentResult

        name = getattr(cls, "spec_name", None)
        if not (isinstance(cls, type) and issubclass(cls, Component)):
            raise SpecError(f"{cls!r} is not a Component subclass")
        spec = self._specs.get(str(name))
        if not isinstance(spec, ComponentSpec):
            raise SpecError(
                f"No component spec for class {cls.__name__} (spec_name={name!r})",
                [
                    ErrorDetail(
                        type="spec_not_found",
                        msg=f"'{name}' has no component YAML spec",
                        hint=suggest(str(name), self._specs) or "add a YAML file to the domain's spec directory",
                    )
                ],
            )
        errors: list[ErrorDetail] = []
        pm, rm = getattr(cls, "Params", None), getattr(cls, "Result", None)
        if not (isinstance(pm, type) and issubclass(pm, ComponentParams)):
            errors.append(ErrorDetail(loc=("Params",), type="bad_model", msg="Params must subclass ComponentParams"))
        if not (isinstance(rm, type) and issubclass(rm, ComponentResult)):
            errors.append(ErrorDetail(loc=("Result",), type="bad_model", msg="Result must subclass ComponentResult"))
        if not errors:
            code, declared = set(pm.model_fields), set(spec.params)  # ty: ignore[unresolved-attribute]
            errors += [
                ErrorDetail(loc=("params", f), type="spec_only_param", msg="declared in the spec but missing in Params")
                for f in sorted(declared - code)
            ]
            errors += [
                ErrorDetail(
                    loc=("params", f), type="undocumented_param", msg="present in Params but not documented in the spec"
                )
                for f in sorted(code - declared)
            ]
        for port, ps in {**spec.inputs, **spec.outputs}.items():
            if not self.types.has(ps.type):
                errors.append(
                    ErrorDetail(
                        loc=("ports", port, "type"),
                        type="unknown_type",
                        input=ps.type,
                        msg=f"artifact type '{ps.type}' is not registered",
                        hint=suggest(ps.type, self.types.names()) or f"available: {self.types.names()}",
                    )
                )
        if errors:
            raise SpecError(f"Contract mismatch between spec '{name}' and {cls.__name__}", errors, component=name)
        self._components[spec.name] = cls(spec, self.types)  # parses port constraints (may raise SpecError)

    def register_pipeline(self, pspec: PipelineSpec) -> None:
        """Validate a `PipelineSpec` against the registry and register it; unless ``expose_as_component`` is false it is also registered as a component, so pipelines can be steps of other pipelines."""
        from .pipeline import PipelineComponent, validate_pipeline_spec

        validate_pipeline_spec(pspec, self)
        self._specs[pspec.name] = pspec
        self._pipelines[pspec.name] = pspec
        if pspec.expose_as_component:
            self._components[pspec.name] = PipelineComponent.from_spec(pspec, self)

    def load_domain(
        self,
        spec_dir: str | Path | None = None,
        classes: Iterable[type] | None = None,
        specs: Iterable[AnySpec] | None = None,
    ) -> list[str]:
        """Load a domain pack: specs, then components, then pipelines (dependency order).

        Loading the same ``spec_dir`` twice is a no-op (resolved path), so ``--domains dir``
        and ``fabric.md`` ``skill_dirs`` may point at the same directory.
        """
        key = Path(spec_dir).resolve() if spec_dir is not None else None
        if key is not None and key in self._loaded_dirs and specs is None and classes is None:
            return self._loaded_dirs[key]
        dir_specs = [] if key in self._loaded_dirs else (load_spec_dir(spec_dir) if spec_dir else [])
        loaded = list(specs or []) + dir_specs
        self.add_specs(loaded)
        names = {s.name for s in loaded} | set(self._loaded_dirs.get(key, ()))
        for cls in classes if classes is not None else declared_components():
            spec = getattr(cls, "spec_name", None)
            if spec in names and spec not in self._components:
                self.register(cls)
        for s in loaded:  # 'runtime: prompt' skills need no Python class
            if isinstance(s, ComponentSpec) and s.runtime == "prompt" and s.name not in self._components:
                from .prompt import PromptComponent

                self._components[s.name] = PromptComponent.from_spec(s, self.types)
        missing = [s.name for s in loaded if isinstance(s, ComponentSpec) and s.name not in self._components]
        if missing:
            raise SpecError(
                f"Component specs without implementation: {missing}",
                [
                    ErrorDetail(
                        loc=("components", m),
                        type="implementation_missing",
                        msg="no @component class registered for this spec",
                    )
                    for m in missing
                ],
            )
        pending = [s for s in loaded if isinstance(s, PipelineSpec)]
        while pending:
            ready = [p for p in pending if all(st.component in self._components for st in p.steps)]
            if not ready:  # report the first blocker precisely
                self.register_pipeline(pending[0])
            for p in ready:
                self.register_pipeline(p)
            pending = [p for p in pending if p not in ready]
        if key is not None:
            self._loaded_dirs[key] = sorted(set(self._loaded_dirs.get(key, ())) | names)
        return sorted(names)

    def discover_domains(self) -> list[str]:
        """Load every installed domain pack advertised through the ``agent_fabric.domains`` entry point; returns the entry point names loaded."""
        found = []
        from .compat import check_pack_api

        for ep in metadata.entry_points(group=DOMAIN_ENTRY_POINT):
            register = ep.load()
            check_pack_api(register, ep.name)
            register(self)
            found.append(ep.name)
        return found

    # ------------------------------------------------------------ queries
    def get(self, name: str) -> Any:
        """The registered component by name; raises a `SpecError` with a spelling suggestion when unknown."""
        try:
            return self._components[name]
        except KeyError:
            raise SpecError(
                f"Unknown component '{name}'",
                [
                    ErrorDetail(
                        type="unknown_component",
                        msg=f"'{name}' is not registered",
                        input=name,
                        hint=suggest(name, self._components) or f"available: {self.names()}",
                    )
                ],
            ) from None

    def has(self, name: str) -> bool:
        """Whether an enabled component with this name is registered."""
        return name in self._components and self._components[name].spec.enabled

    def names(self, domains: Iterable[str] | None = None) -> list[str]:
        """Sorted names of enabled components, optionally limited to the given ``domains`` (``core`` components are always included)."""
        doms = set(domains) if domains else None
        return sorted(
            n
            for n, c in self._components.items()
            if c.spec.enabled and (doms is None or c.spec.domain in doms or c.spec.domain == "core")
        )

    def domains(self) -> list[str]:
        """Sorted names of the domains that have at least one registered component."""
        return sorted({c.spec.domain for c in self._components.values()})

    def spec(self, name: str) -> Any:
        """The spec (contract and guidance) of a registered component."""
        return self.get(name).spec

    def pipeline(self, name: str) -> PipelineSpec:
        """The registered `PipelineSpec` by name; raises a `SpecError` with a suggestion when unknown."""
        if name not in self._pipelines:
            raise SpecError(
                f"Unknown pipeline '{name}'",
                [
                    ErrorDetail(
                        type="unknown_pipeline",
                        msg=f"'{name}' is not registered",
                        input=name,
                        hint=suggest(name, self._pipelines) or f"available: {sorted(self._pipelines)}",
                    )
                ],
            )
        return self._pipelines[name]

    def guidance(self, name: str, section: str | None = None, max_chars: int | None = None) -> str:
        """Progressive disclosure: the full SKILL.md body (or one section) of a component, on demand."""
        g = self.spec(name).guidance
        return g.section(section, max_chars) if section else g.body

    def pipelines(self) -> list[str]:
        """Sorted names of the registered pipelines."""
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
                t = prop.get("type") or [
                    a.get("type") for a in prop.get("anyOf", []) if a.get("type") not in (None, "null")
                ]
                if "enum" in prop:
                    t = f"one of {prop['enum']}"
                entry = {
                    "type": t or "any",
                    "required": pname in schema.get("required", []),
                    "doc": spec.params[pname].description,
                }
                if not compact and "default" in prop:
                    entry["default"] = prop["default"]
                params[pname] = entry
            item: dict[str, Any] = {
                "name": name,
                "domain": spec.domain,
                "description": spec.description,
                "when_to_use": spec.when_to_use,
                "params": params,
                "inputs": {p: f"{ps.type}{'' if ps.required else ' (optional)'}" for p, ps in spec.inputs.items()},
                "outputs": {"result": "json", **{p: ps.type for p, ps in spec.outputs.items()}},
            }
            if spec.avoid_when:
                item["avoid_when"] = spec.avoid_when
            out.append(item)
        return out


__all__ = [
    "DOMAIN_ENTRY_POINT",
    "Registry",
    "component",
    "declared_components",
]
