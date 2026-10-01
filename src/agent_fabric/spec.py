"""Declarative specs: components and pipelines.

A **component spec** declares *what* a component needs and produces (typed ports,
parameter docs, LLM hints). The Python class declares *how*. The registry verifies
both agree before the component can be used.

A **pipeline spec** is a named, parameterised DAG of components. Registered
pipelines become components themselves (composite), so pipelines nest.

Two interchangeable file formats produce the same models:
* ``SKILL.md`` (recommended) - YAML frontmatter = contract, Markdown body = guidance for LLMs
  (see :mod:`agent_fabric.markdown`); lives in ``skills/<name>/SKILL.md`` (+ optional ``references/``);
* ``*.yaml`` - contract only (``llm:`` block for hints); kept for backward compatibility.

File kind is selected by the top-level ``kind`` key: ``component`` (default) or ``pipeline``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ErrorDetail, SpecError, details_from_pydantic
from .markdown import (
    COMMON_MISTAKES,
    INTERPRETING,
    WHEN_NOT_TO_USE,
    WHEN_TO_USE,
    Guidance,
    first_paragraph,
    guidance_from,
    read_markdown,
)

NAME = r"^[a-z][a-z0-9_]*$"
RESULT_PORT = "result"  # implicit JSON output of every component (its Result model)


class PortSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "any"
    required: bool = True
    description: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict, description="validated by the artifact type")


class ParamDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    example: Any = None
    required: bool = False
    default: Any = None


class LLMHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    when_to_use: str
    avoid_when: str | None = None
    interpretation_focus: list[str] = Field(default_factory=list)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=NAME)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    title: str = ""
    description: str = Field(min_length=3, description="one line; shown in planner catalogues")
    domain: str = Field("core", pattern=NAME)
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    llm: LLMHints | None = Field(None, description="YAML-style hints; SKILL.md bodies supersede them")
    guidance: Guidance = Field(default_factory=Guidance)
    enabled: bool = True

    @model_validator(mode="after")
    def _title(self) -> _Base:
        if not self.title:
            self.title = self.name.replace("_", " ").capitalize()
        return self

    # ---- guidance accessors (body sections win over YAML hints; description is the last resort)
    @property
    def when_to_use(self) -> str:
        text = self.guidance.section(WHEN_TO_USE)
        return first_paragraph(text) if text else (self.llm.when_to_use if self.llm else self.description)

    @property
    def avoid_when(self) -> str | None:
        text = self.guidance.section(WHEN_NOT_TO_USE)
        return first_paragraph(text) if text else (self.llm.avoid_when if self.llm else None)

    @property
    def interpretation_guide(self) -> str:
        text = self.guidance.section(INTERPRETING, max_chars=1500)
        if text:
            return text
        return (
            ", ".join(self.llm.interpretation_focus) if self.llm and self.llm.interpretation_focus else "main results"
        )

    @property
    def common_mistakes(self) -> str:
        return self.guidance.section(COMMON_MISTAKES, max_chars=1200)


class PromptOptions(BaseModel):
    """Tuning for ``runtime: prompt`` components (all optional, LiteLLM aliases only)."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(None, description="LiteLLM proxy alias; None = the run's interpreter model")
    temperature: float | None = Field(None, ge=0, le=2)
    grounding: bool = Field(True, description="reject output numbers that do not appear in the inputs/params")


class ComponentSpec(_Base):
    kind: Literal["component"] = "component"
    runtime: Literal["code", "prompt"] = "code"
    params: dict[str, ParamDoc] = Field(default_factory=dict)
    inputs: dict[str, PortSpec] = Field(default_factory=dict)
    outputs: dict[str, PortSpec] = Field(
        default_factory=dict, description=f"extra outputs; '{RESULT_PORT}' is implicit"
    )
    prompt: PromptOptions | None = Field(None, description="prompt-runtime options (model, temperature, grounding)")

    @model_validator(mode="after")
    def _ports(self) -> ComponentSpec:
        bad = [p for p in [*self.inputs, *self.outputs] if not re.match(NAME, p)]
        if bad:
            raise ValueError(f"port names must be snake_case: {bad}")
        if RESULT_PORT in self.outputs:
            raise ValueError(f"'{RESULT_PORT}' is reserved (implicit Result output)")
        if self.runtime == "code" and self.prompt is not None:
            raise ValueError("'prompt' options require 'runtime: prompt'")
        return self


class PipelineParam(ParamDoc):
    """Pipeline params are substituted into step params via ``$params.<name>`` (see ``instantiate``)."""


class StepTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    component: str
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = ""


class PipelineSpec(_Base):
    kind: Literal["pipeline"] = "pipeline"
    params: dict[str, PipelineParam] = Field(default_factory=dict)
    inputs: dict[str, PortSpec] = Field(default_factory=dict)
    steps: list[StepTemplate] = Field(min_length=1)
    outputs: dict[str, str] = Field(default_factory=dict, description="exposed name -> 'step.port' reference")
    expose_as_component: bool = True

    @model_validator(mode="after")
    def _param_refs(self) -> PipelineSpec:
        refs: set[str] = set()

        def walk(v: Any) -> None:
            if isinstance(v, str) and v.startswith("$params."):
                refs.add(v.split(".", 1)[1])
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)

        for st in self.steps:
            walk(st.params)
        unknown = sorted(refs - set(self.params))
        if unknown:
            raise ValueError(f"steps reference undeclared pipeline params: {unknown}")
        return self

    def instantiate(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a raw plan dict with every ``"$params.x"`` value substituted."""
        from .errors import ErrorDetail, ParamsValidationError, suggest

        params = dict(params or {})
        errors = [
            ErrorDetail(
                loc=("params", k),
                type="extra_forbidden",
                msg="unknown pipeline parameter",
                hint=suggest(k, self.params) or f"allowed: {sorted(self.params)}",
            )
            for k in params
            if k not in self.params
        ]
        values = {}
        for k, p in self.params.items():
            if k in params:
                values[k] = params[k]
            elif p.required:
                errors.append(
                    ErrorDetail(loc=("params", k), type="missing", msg=f"pipeline parameter '{k}' is required")
                )
            else:
                values[k] = p.default
        if errors:
            raise ParamsValidationError(f"Invalid parameters for pipeline '{self.name}'", errors, component=self.name)

        def sub(v: Any) -> Any:
            if isinstance(v, str) and v.startswith("$params."):
                return values[v.split(".", 1)[1]]
            if isinstance(v, dict):
                return {k: sub(x) for k, x in v.items()}
            if isinstance(v, list):
                return [sub(x) for x in v]
            return v

        steps = []
        for s in self.steps:
            d = s.model_dump()
            # a $params reference resolving to None is dropped so the component default applies
            d["params"] = {k: v2 for k, v in d["params"].items() if (v2 := sub(v)) is not None}
            steps.append(d)
        return {"objective": self.title, "steps": steps, "outputs": dict(self.outputs)}


AnySpec = ComponentSpec | PipelineSpec


SKILL_FILE = "SKILL.md"


def _validate(raw: dict[str, Any], where: str) -> AnySpec:
    model = PipelineSpec if raw.get("kind") == "pipeline" else ComponentSpec
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise SpecError(f"Spec {where} is invalid", details_from_pydantic(exc, (where,))) from exc


def load_spec(path: str | Path) -> AnySpec:
    path = Path(path)
    if path.suffix.lower() == ".md":
        doc = read_markdown(path)
        raw = dict(doc.meta)
        if "guidance" in raw:
            raise SpecError(f"{path}: 'guidance' is derived from the body and cannot be set in frontmatter")
        raw.setdefault("title", doc.title or "")
        raw["guidance"] = guidance_from(doc)
        spec = _validate(raw, str(path))
        if path.name == SKILL_FILE and path.parent.name != spec.name:
            raise SpecError(
                f"{path}: skill folder and name differ",
                [
                    ErrorDetail(
                        loc=(str(path), "name"),
                        type="name_mismatch",
                        msg=f"folder '{path.parent.name}' != name '{spec.name}'",
                        hint="rename the folder or the 'name' field so they match",
                    )
                ],
            )
        return spec
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SpecError(f"Spec file {path.name} is not valid YAML: {exc}") from exc
    return _validate(raw, path.name)


def spec_files(directory: str | Path) -> list[Path]:
    """``**/SKILL.md`` and ``**/*.yaml|yml`` (files under ``references/`` are never specs)."""
    root = Path(directory)
    files = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and "references" not in p.relative_to(root).parts
        and (p.name == SKILL_FILE or p.suffix.lower() in (".yaml", ".yml"))
    ]
    return sorted(files)


def load_spec_dir(directory: str | Path) -> list[AnySpec]:
    """Load every spec under ``directory``; all problems are reported together."""
    specs, details = [], []
    for p in spec_files(directory):
        try:
            specs.append(load_spec(p))
        except SpecError as exc:
            details += exc.details or [ErrorDetail(loc=(str(p),), type="invalid_spec", msg=exc.message)]
    names = [s.name for s in specs]
    details += [
        ErrorDetail(loc=(str(directory),), type="duplicate_name", msg=f"'{n}' defined more than once")
        for n in sorted({n for n in names if names.count(n) > 1})
    ]
    if details:
        raise SpecError(f"{len(details)} problem(s) in specs under {directory}", details)
    return specs
