"""Drift lint for SKILL.md / AGENT.md: keeps natural-language guidance consistent with the contracts.

Loading already rejects anything that breaks a contract (bad frontmatter, unknown ports,
invalid trees). The lint adds what loading cannot know - *prose* that drifted:

* skill bodies that mention `identifiers` which are not params, ports, outputs or known names;
* missing canonical sections (``## When to use`` for components, ``## Procedure`` for pipelines);
* broken relative links (e.g. ``references/x.md``);
* descriptions and bodies over their context budgets (they are sent to small local models);
* agent bodies that mention `agent_names` that are not sub-agents / declared agents.

CLI (non-zero exit on errors, and on warnings with ``--strict``)::

    python -m agent_fabric.lint --domains stat_fabric.domain:register text_pack:register \\
                                --agents config [--strict]
    python -m agent_fabric.lint --agents examples/notes                 # code-free pack via fabric.md skill_dirs
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .errors import FabricError
from .markdown import PROCEDURE, WHEN_TO_USE

DESCRIPTION_MAX = 200
SKILL_BODY_MAX = 6000
AGENT_BODY_MAX = 4000
_TICK = re.compile(r"`([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?)`")
_LINK = re.compile(r"\]\(([^)#\s]+)\)")
# snake_case words that commonly appear in prose and are not identifiers
ALLOW = {
    "p_value",
    "p_adj",
    "r_squared",
    "adj_r_squared",
    "n_used",
    "f_value",
    "eta_sq_partial",
    "true",
    "false",
    "null",
    "none",
    "depends_on",
    "sub_agents",
    "output_schema",
    "check_grounding",
}


class LintIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    where: str
    msg: str
    hint: str | None = None

    def __str__(self) -> str:
        return f"{self.severity.upper():7} {self.code:22} {self.where}: {self.msg}" + (
            f"  ({self.hint})" if self.hint else ""
        )


def _links(body: str, source: str | None, where: str) -> list[LintIssue]:
    if not source:
        return []
    base = Path(source).parent
    out = []
    for target in _LINK.findall(body):
        if "://" in target or target.startswith("mailto:"):
            continue
        if not (base / target).exists():
            out.append(
                LintIssue(
                    severity="error", code="broken_link", where=where, msg=f"link target '{target}' does not exist"
                )
            )
    return out


def _result_fields(comp: Any) -> set[str]:
    names: set[str] = set()

    def walk(model: Any) -> None:
        for fname, f in getattr(model, "model_fields", {}).items():
            names.add(fname)
            ann = f.annotation
            for arg in getattr(ann, "__args__", ()) or (ann,):
                if isinstance(arg, type) and issubclass(arg, BaseModel) and arg is not model:
                    walk(arg)

    walk(comp.Result)
    return names


def lint_skills(registry: Any) -> list[LintIssue]:
    issues: list[LintIssue] = []
    known_global = set(registry.names()) | set(registry.pipelines()) | set(registry.types.names())
    for name in registry.names():
        comp = registry.get(name)
        spec = comp.spec
        where = spec.guidance.source or f"{name} (yaml)"
        is_pipeline = name in registry.pipelines()
        if len(spec.description) > DESCRIPTION_MAX:
            issues.append(
                LintIssue(
                    severity="warning",
                    code="description_too_long",
                    where=where,
                    msg=f"{len(spec.description)} chars (max {DESCRIPTION_MAX})",
                    hint="the description is sent in every planner catalogue; move detail to the body",
                )
            )
        body = spec.guidance.body
        if not body:
            if spec.llm is None:
                issues.append(
                    LintIssue(
                        severity="warning",
                        code="no_guidance",
                        where=where,
                        msg="no SKILL.md body and no llm hints",
                        hint="add '## When to use'",
                    )
                )
            continue
        needed = PROCEDURE if is_pipeline else WHEN_TO_USE
        if not spec.guidance.section(needed):
            issues.append(
                LintIssue(
                    severity="warning",
                    code="missing_section",
                    where=where,
                    msg=f"no '## {needed.capitalize()}' section",
                )
            )
        if len(body) > SKILL_BODY_MAX:
            issues.append(
                LintIssue(
                    severity="warning",
                    code="body_too_long",
                    where=where,
                    msg=f"{len(body)} chars (max {SKILL_BODY_MAX})",
                    hint="move material to references/",
                )
            )
        pspec = registry.pipeline(name) if is_pipeline else None
        known = (
            known_global
            | set(spec.params)
            | set(spec.inputs)
            | set(spec.outputs)
            | {"result"}
            | _result_fields(comp)
            | ALLOW
            | {s.id for s in (pspec.steps if pspec else [])}
        )
        for ident in sorted(set(_TICK.findall(body))):
            head = ident.split(".")[0]
            if "_" in ident.replace(".", "") and ident not in known and head not in known:
                issues.append(
                    LintIssue(
                        severity="warning",
                        code="unknown_identifier",
                        where=where,
                        msg=f"`{ident}` is not a param, port, result field or known name",
                        hint="fix the name or drop the backticks if it is prose",
                    )
                )
        issues += _links(body, spec.guidance.source, where)
    return issues


def lint_agents(fabric: Any) -> list[LintIssue]:
    issues = [
        LintIssue(severity="error", code=d.type, where=".".join(map(str, d.loc)), msg=d.msg, hint=d.hint)
        for d in fabric.validate()
    ]
    names = set(fabric.config.agents)
    for name, spec in fabric.config.agents.items():
        where = spec.source or f"agents.{name}"
        body = spec.instructions
        if not body and not spec.backstory:
            issues.append(
                LintIssue(
                    severity="warning",
                    code="no_instructions",
                    where=where,
                    msg="agent has no AGENT.md body",
                    hint="describe how the agent should work",
                )
            )
        if len(body) > AGENT_BODY_MAX:
            issues.append(
                LintIssue(
                    severity="warning",
                    code="body_too_long",
                    where=where,
                    msg=f"{len(body)} chars (max {AGENT_BODY_MAX})",
                    hint="move material to references/",
                )
            )
        for ident in sorted(set(_TICK.findall(body))):
            if "_" in ident and ident not in names and ident not in ALLOW and not fabric.registry.has(ident):
                issues.append(
                    LintIssue(
                        severity="warning",
                        code="unknown_identifier",
                        where=where,
                        msg=f"`{ident}` is not an agent, component or pipeline name",
                    )
                )
        mentioned = {i for i in _TICK.findall(body) if i in names and i != name}
        stray = sorted(mentioned - set(spec.sub_agents))
        if spec.sub_agents and stray:
            issues.append(
                LintIssue(
                    severity="warning",
                    code="not_a_sub_agent",
                    where=where,
                    msg=f"body mentions {stray} but they are not in sub_agents",
                )
            )
        missing = sorted(set(spec.sub_agents) - {i for i in _TICK.findall(body)}) if body and spec.sub_agents else []
        if missing and spec.strategy == "router":
            issues.append(
                LintIssue(
                    severity="warning",
                    code="undocumented_sub_agent",
                    where=where,
                    msg=f"router body never mentions sub-agents {missing}",
                    hint="say when to delegate to each one",
                )
            )
        issues += _links(body, spec.source, where)
    return issues


def _load_callable(ref: str) -> Any:
    mod, _, attr = ref.partition(":")
    return getattr(importlib.import_module(mod), attr or "register")


def collect_issues(domains: Iterable[str], agents: str | None = None, schemas: Iterable[str] = ()) -> list[LintIssue]:
    """Load everything and return all issues (raises ``FabricError`` if a domain fails to load).

    ``domains`` entries are ``module:register`` references or plain spec directories
    (code-free packs). ``skill_dirs`` from the agents config are loaded too, so
    Markdown-only skills are linted like any component."""
    from . import build_registry
    from .agents import AgentFabric, AgentsConfig

    registry = build_registry(list(domains))
    issues: list[LintIssue] = []
    fabric = None
    if agents:
        try:
            fabric = AgentFabric(registry, AgentsConfig.load(agents))  # loads fabric.md 'skill_dirs'
            for ref in schemas:
                for n, model in _load_callable(ref).items():
                    fabric.register_schema(n, model)
        except FabricError as exc:
            issues += [
                LintIssue(severity="error", code=d.type, where=".".join(map(str, d.loc)), msg=d.msg, hint=d.hint)
                for d in exc.details
            ] or [LintIssue(severity="error", code="load_failed", where=agents, msg=exc.message)]
    issues += lint_skills(registry)
    if fabric is not None:
        issues += lint_agents(fabric)
    return issues


def run(domains: Iterable[str], agents: str | None, strict: bool = False, schemas: Iterable[str] = ()) -> int:
    try:
        issues = collect_issues(domains, agents, schemas)
    except FabricError as exc:
        print(f"ERROR   load failed: {exc.message}")
        for d in exc.details:
            print(f"        {'.'.join(map(str, d.loc))}: {d.msg}" + (f" ({d.hint})" if d.hint else ""))
        return 2
    for i in issues:
        print(i)
    errors = sum(i.severity == "error" for i in issues)
    warnings = len(issues) - errors
    print(f"{errors} error(s), {warnings} warning(s)")
    return 1 if errors or (strict and warnings) else 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m agent_fabric.lint", description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--domains", nargs="*", default=[], help="module:register callables or spec directories (code-free packs)"
    )
    ap.add_argument("--agents", help="agents directory (fabric.md + agents/*/AGENT.md) or YAML file")
    ap.add_argument(
        "--schemas", nargs="*", default=[], help="module:MAPPING of output schemas, e.g. stat_fabric.schemas:SCHEMAS"
    )
    ap.add_argument("--strict", action="store_true", help="fail on warnings too")
    a = ap.parse_args(argv)
    sys.exit(run(a.domains, a.agents, a.strict, a.schemas))


if __name__ == "__main__":
    main()
