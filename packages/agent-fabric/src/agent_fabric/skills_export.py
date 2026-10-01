"""Export fabric skills as spec-compliant Agent Skills (https://agentskills.io/specification).

agent-fabric's own ``SKILL.md`` is a superset: its frontmatter carries the executable contract (params, ports, steps, ...)
and snake_case names. The Agent Skills format allows only ``name``, ``description``, ``license``, ``compatibility``,
``metadata`` (string -> string) and ``allowed-tools``, and kebab-case names, so the export produces a *view* of each skill:

* ``name``: the component name with ``_`` -> ``-`` (the original is kept in ``metadata.fabric-name``); directory = name;
* ``description``: description + the first paragraph of ``## When to use`` (what it does and when), at most 1024 chars;
* ``metadata``: version, domain, category, kind, runtime, contract summary (all strings);
* body: the original guidance plus a generated ``## Contract`` section; ``references/`` is copied.

The source of truth stays the fabric ``SKILL.md``; nothing is read back from the export.
``validate_skill_dir`` mirrors the reference validator's rules so CI can check the output.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .errors import ErrorDetail, SpecError
from .markdown import read_markdown
from .spec import SKILL_FILE, ComponentSpec, PipelineSpec

NAME_MAX, DESCRIPTION_MAX, COMPATIBILITY_MAX = 64, 1024, 500
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def export_name(name: str) -> str:
    return name.replace("_", "-")


def export_description(spec: ComponentSpec | PipelineSpec) -> str:
    desc = " ".join(spec.description.split())
    when = spec.when_to_use
    if when and when != spec.description and when not in desc:
        desc = f"{desc.rstrip('.')}. When to use: {when}"
    return desc if len(desc) <= DESCRIPTION_MAX else desc[: DESCRIPTION_MAX - 1].rsplit(" ", 1)[0] + "…"


def _ports(ports: dict[str, Any]) -> str:
    return ", ".join(f"{n}:{p.type}" if hasattr(p, "type") else f"{n}={p}" for n, p in ports.items())


def contract_section(spec: ComponentSpec | PipelineSpec) -> str:
    lines = [
        "## Contract (agent-fabric)",
        "",
        f"Executed by the agent-fabric runtime (`{spec.domain}` domain); the contract is enforced by code, not by the model.",
        "",
    ]
    for pname, p in spec.params.items():
        flags = ", ".join(
            x
            for x in (
                "required" if p.required else "optional",
                f"default {p.default!r}" if p.default is not None else "",
            )
            if x
        )
        lines.append(f"- param `{pname}` ({flags}): {p.description}")
    for pname, port in spec.inputs.items():
        lines.append(
            f"- input `{pname}` ({port.type}{'' if port.required else ', optional'}): {port.description}".rstrip(": ")
        )
    if isinstance(spec, ComponentSpec):
        lines.append("- output `result`: the JSON result of the component")
        lines += [f"- output `{n}` ({p.type}): {p.description}".rstrip(": ") for n, p in spec.outputs.items()]
    else:
        lines += [f"- output `{n}` = `{ref}`" for n, ref in spec.outputs.items()]
        lines += ["", "Steps: " + " -> ".join(f"`{s.id}` ({s.component})" for s in spec.steps)]
    return "\n".join(lines) + "\n"


def export_skill(spec: ComponentSpec | PipelineSpec, out_dir: str | Path, license_id: str = "MIT") -> Path:
    """Write ``<out_dir>/<kebab-name>/SKILL.md`` (+ references/) for one spec; returns the skill directory."""
    name = export_name(spec.name)
    meta: dict[str, str] = {
        "fabric-name": spec.name,
        "version": spec.version,
        "domain": spec.domain,
        "category": spec.category,
        "kind": spec.kind,
        "runtime": spec.runtime if isinstance(spec, ComponentSpec) else "pipeline",
        "params": ", ".join(spec.params) or "none",
        "inputs": _ports(spec.inputs) or "none",
        "outputs": _ports(spec.outputs) if spec.outputs else "result",
    }
    front: dict[str, Any] = {
        "name": name,
        "description": export_description(spec),
        "license": license_id,
        "compatibility": (
            f"Requires the agent-fabric runtime with the '{spec.domain}' domain pack; "
            "not runnable by an agent on its own."
        )[:COMPATIBILITY_MAX],
        "metadata": meta,
    }
    body = spec.guidance.body.strip() or f"# {spec.title}\n\n{spec.description}"
    target = Path(out_dir) / name
    target.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=10_000) + "---\n\n"
    (target / SKILL_FILE).write_text(text + body + "\n\n" + contract_section(spec), encoding="utf-8")
    if spec.guidance.source:
        refs = Path(spec.guidance.source).parent / "references"
        if refs.is_dir():
            shutil.copytree(refs, target / "references", dirs_exist_ok=True)
    return target


def export_registry(registry: Any, out_dir: str | Path) -> list[Path]:
    """Export every skill in a registry (components and pipelines)."""
    specs = [registry.pipeline(n) if n in registry.pipelines() else registry.get(n).spec for n in registry.names()]
    seen: dict[str, str] = {}
    clashes = []
    for spec in specs:
        other = seen.setdefault(export_name(spec.name), spec.name)
        if other != spec.name:
            clashes.append(
                ErrorDetail(
                    loc=(spec.name,),
                    type="export_name_collision",
                    msg=f"'{spec.name}' and '{other}' both export as '{export_name(spec.name)}'",
                    hint="rename one of the skills (names differing only by '_' vs '-' cannot be exported)",
                )
            )
    if clashes:
        raise SpecError(f"{len(clashes)} export name collision(s)", clashes)
    return [export_skill(spec, out_dir) for spec in specs]


def validate_skill_dir(path: str | Path) -> list[str]:
    """Problems of one exported skill directory, using the Agent Skills reference validator's rules."""
    path = Path(path)
    file = path / SKILL_FILE
    if not file.exists():
        return [f"{path}: no {SKILL_FILE}"]
    try:
        meta = read_markdown(file).meta
    except Exception as exc:  # parse errors are validator findings, not crashes
        return [f"{file}: unreadable frontmatter ({exc})"]
    errors: list[str] = []
    if extra := sorted(set(meta) - ALLOWED_KEYS):
        errors.append(f"unexpected fields in frontmatter: {extra}; only {sorted(ALLOWED_KEYS)} are allowed")
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        errors.append("name is required")
    else:
        if len(name) > NAME_MAX:
            errors.append(f"name longer than {NAME_MAX} chars")
        if not _KEBAB.match(name):
            errors.append(f"name '{name}' must be lowercase letters, digits and single hyphens, not start/end with one")
        if name != path.name:
            errors.append(f"name '{name}' must match the directory '{path.name}'")
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("description is required and non-empty")
    elif len(desc) > DESCRIPTION_MAX:
        errors.append(f"description longer than {DESCRIPTION_MAX} chars")
    compat = meta.get("compatibility")
    if compat is not None and (not isinstance(compat, str) or not 1 <= len(compat) <= COMPATIBILITY_MAX):
        errors.append(f"compatibility must be a string of 1-{COMPATIBILITY_MAX} chars")
    md = meta.get("metadata")
    if md is not None and not (
        isinstance(md, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in md.items())
    ):
        errors.append("metadata must map string keys to string values")
    if "allowed-tools" in meta and not isinstance(meta["allowed-tools"], str):
        errors.append("allowed-tools must be a space-separated string")
    if "license" in meta and not isinstance(meta["license"], str):
        errors.append("license must be a string")
    return [f"{file}: {e}" for e in errors]


def validate_tree(root: str | Path) -> list[str]:
    return [e for d in sorted(Path(root).iterdir()) if d.is_dir() for e in validate_skill_dir(d)]


__all__ = [
    "export_description",
    "export_name",
    "export_registry",
    "export_skill",
    "validate_skill_dir",
    "validate_tree",
]
