"""Agent specs: agents are *declared* as a tree and *built* by registered builders.

Recommended layout (Markdown, one folder per agent)::

    config/
      fabric.md                     frontmatter: root, budget, llm   (body: human documentation)
      agents/<name>/AGENT.md        frontmatter: contract (kind, sub_agents, ...)   body: instructions
      agents/<name>/references/     optional long material, never loaded automatically

A single ``agents.yaml`` with the same fields is still accepted (``AgentsConfig.from_yaml``).

    agents:
      lead:        {kind: supervisor, strategy: router, sub_agents: [stats_team, writer]}
      stats_team:  {kind: supervisor, strategy: sequential, sub_agents: [planner, reviewer]}
      planner:     {kind: planner, domains: [statistics], fallback: stats_rules}
      ...

Kinds (built-in): ``llm`` | ``planner`` | ``pipeline`` | ``function`` | ``supervisor``.
Domain packs and users add kinds/backends with ``@AgentFabric.builder(kind, backend)``.
The tree is validated as a whole (references, cycles, depth, capabilities) before anything runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import AgentConfigError, ErrorDetail, SpecError, details_from_pydantic
from ..llm.backends import LLMSettings
from ..markdown import first_paragraph, read_markdown
from .runtime import BudgetSettings

AGENT_NAME = r"^[a-z][a-z0-9_]{0,39}$"


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, description="Markdown only: must equal the folder name")
    kind: str
    backend: str = "fabric"
    role: str = ""
    goal: str = ""
    backstory: str = ""
    instructions: str = Field("", description="AGENT.md body: the agent's working instructions (system prompt)")
    source: str | None = Field(None, description="file the spec was loaded from")
    description: str = Field("", description="what a parent router sees when choosing this agent (default: goal)")
    model: str | None = Field(None, description="LiteLLM proxy alias; None = settings default for the kind")
    temperature: float | None = Field(None, ge=0, le=2)
    max_retries: int | None = Field(None, ge=1, le=6)
    fallback: str | None = Field(None, description="backend used when this one fails to build or run")
    # composition
    sub_agents: list[str] = Field(default_factory=list)
    strategy: Literal["router", "sequential"] = "router"
    synthesize: bool = True
    max_delegations: int = Field(6, ge=1, le=20)
    # capabilities
    domains: list[str] = Field(default_factory=list, description="planner: component domains it may use")
    pipeline: str | None = Field(None, description="pipeline kind: registered pipeline name")
    function: str | None = Field(None, description="function kind: registered function name")
    output_schema: str | None = Field(None, description="registered pydantic schema for structured output")
    interpret: Literal["rules", "llm", "none"] = "rules"
    inputs: list[str] = Field(default_factory=list, description="default blackboard keys this agent reads")
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_purpose(self) -> "AgentSpec":
        if not (self.goal or self.description or self.instructions):
            raise ValueError("an agent needs a goal, a description or instructions (AGENT.md body)")
        return self

    @property
    def card(self) -> str:
        """What a parent router sees: description > goal > first paragraph of instructions."""
        return self.description or self.goal or first_paragraph(self.instructions, 200)


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    root: str | None = None
    agents: dict[str, AgentSpec]

    @model_validator(mode="after")
    def _names(self) -> "AgentsConfig":
        import re

        bad = [n for n in self.agents if not re.match(AGENT_NAME, n)]
        if bad:
            raise ValueError(f"agent names must be snake_case (<= 40 chars): {bad}")
        if self.root is not None and self.root not in self.agents:
            raise ValueError(f"root '{self.root}' is not a declared agent")
        return self

    @classmethod
    def load(cls, path: str | Path) -> "AgentsConfig":
        """Directory (fabric.md + agents/*/AGENT.md), a fabric.md file, or a YAML file."""
        path = Path(path)
        if path.is_dir():
            return cls.from_dir(path)
        if path.suffix.lower() == ".md":
            return cls.from_dir(path.parent)
        return cls.from_yaml(path)

    @classmethod
    def from_dir(cls, directory: str | Path) -> "AgentsConfig":
        root = Path(directory)
        details: list[ErrorDetail] = []
        header: dict[str, Any] = {}
        for candidate in ("fabric.md", "fabric.yaml", "fabric.yml"):
            f = root / candidate
            if f.is_file():
                try:
                    header = read_markdown(f).meta if f.suffix == ".md" else (yaml.safe_load(f.read_text(encoding="utf-8")) or {})
                except SpecError as exc:
                    details += exc.details
                break
        if "agents" in header:
            details.append(ErrorDetail(loc=("fabric.md", "agents"), type="agents_in_header",
                                       msg="declare agents as agents/<name>/AGENT.md, not in fabric.md"))
        agents: dict[str, Any] = {}
        files = sorted((root / "agents").glob("*/AGENT.md"))
        if not files:
            details.append(ErrorDetail(loc=(str(root / "agents"),), type="no_agents", msg="no agents/<name>/AGENT.md files found"))
        for f in files:
            rel = str(f.relative_to(root))
            try:
                doc = read_markdown(f)
            except SpecError as exc:
                details += exc.details
                continue
            meta = dict(doc.meta)
            for forbidden in ("instructions", "source"):
                if forbidden in meta:
                    details.append(ErrorDetail(loc=(rel, forbidden), type="derived_field",
                                               msg=f"'{forbidden}' comes from the file itself", hint="remove it from the frontmatter"))
                    meta.pop(forbidden)
            name = meta.get("name") or f.parent.name
            if name != f.parent.name:
                details.append(ErrorDetail(loc=(rel, "name"), type="name_mismatch",
                                           msg=f"folder '{f.parent.name}' != name '{name}'", hint="make them equal"))
                continue
            meta.update(name=name, instructions=doc.body, source=str(f))
            try:
                agents[name] = AgentSpec.model_validate(meta)
            except ValidationError as exc:
                details += details_from_pydantic(exc, (rel,))
        if details:
            raise AgentConfigError(f"{len(details)} problem(s) in agent files under {root}", details)
        try:
            return cls.model_validate({**header, "agents": agents})
        except ValidationError as exc:
            raise AgentConfigError(f"Invalid fabric.md under {root}", details_from_pydantic(exc, ("fabric.md",))) from exc

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentsConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(raw, source=Path(path).name)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], source: str = "<dict>") -> "AgentsConfig":
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise AgentConfigError(f"Invalid agents config {source}", details_from_pydantic(exc)) from exc

    def roots(self) -> list[str]:
        if self.root:
            return [self.root]
        children = {c for a in self.agents.values() for c in a.sub_agents}
        return [n for n in self.agents if n not in children]

    def by_kind(self, kind: str) -> list[str]:
        return [n for n, a in self.agents.items() if a.kind == kind]
