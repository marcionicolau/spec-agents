"""Contract-vs-version check: a SKILL.md contract change must come with a matching ``version:`` bump.

    python -m agent_fabric.contracts --base origin/main [--root .]

Compares every ``SKILL.md`` in the working tree with the same file at the git ``--base`` revision.
The *contract* is what callers and planners depend on: kind, runtime, params, input/output ports (types,
required, constraints) and, for pipelines, the exposed outputs. Prose, descriptions and examples are not contract.

* ``major`` (breaking): a param/port removed or its type changed, a param/input becoming required, a new
  required param/input, changed constraints or default, changed kind/runtime, pipeline outputs removed or rewired.
* ``minor`` (compatible): a new optional param/input/output, a default added.
* new skills need no bump; a removed skill is reported as a breaking notice (no version to bump).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .errors import FabricError
from .spec import SKILL_FILE, ComponentSpec, PipelineSpec, load_spec

Level = Literal["none", "minor", "major"]
_ORDER = {"none": 0, "minor": 1, "major": 2}


class ContractIssue(BaseModel):
    severity: Literal["error", "notice"]
    where: str
    msg: str
    hint: str | None = None

    def __str__(self) -> str:
        return f"{self.severity.upper():7} {self.where}: {self.msg}" + (f"  ({self.hint})" if self.hint else "")


def _port(p: Any) -> dict[str, Any]:
    return {"type": p.type, "required": p.required, "constraints": p.constraints}


def contract_of(spec: ComponentSpec | PipelineSpec) -> dict[str, Any]:
    """The part of a spec that callers depend on, as plain data."""
    params = {
        n: {"required": bool(getattr(p, "required", False)), "default": getattr(p, "default", None)}
        for n, p in spec.params.items()
    }
    out: dict[str, Any] = {
        "kind": spec.kind,
        "params": params,
        "inputs": {n: _port(p) for n, p in spec.inputs.items()},
    }
    if isinstance(spec, ComponentSpec):
        out["runtime"] = spec.runtime
        out["outputs"] = {n: _port(p) for n, p in spec.outputs.items()}
    else:
        out["outputs"] = dict(spec.outputs)  # exposed name -> 'step.port'
    return out


def classify(old: dict[str, Any], new: dict[str, Any]) -> tuple[Level, list[str]]:
    """Required bump level and the reasons, comparing two ``contract_of`` dicts."""
    level: Level = "none"
    why: list[str] = []

    def bump(to: Level, reason: str) -> None:
        nonlocal level
        why.append(f"{to}: {reason}")
        if _ORDER[to] > _ORDER[level]:
            level = to

    for key in ("kind", "runtime"):
        if old.get(key) != new.get(key):
            bump("major", f"{key} changed {old.get(key)!r} -> {new.get(key)!r}")

    for name in old["params"].keys() - new["params"].keys():
        bump("major", f"param '{name}' removed")
    for name, p in new["params"].items():
        if name not in old["params"]:
            bump("major" if p["required"] else "minor", f"{'required ' if p['required'] else ''}param '{name}' added")
            continue
        o = old["params"][name]
        if p["required"] and not o["required"]:
            bump("major", f"param '{name}' became required")
        if o["default"] != p["default"]:
            bump(
                "minor" if o["default"] is None else "major",
                f"param '{name}' default {o['default']!r} -> {p['default']!r}",
            )

    for side in ("inputs", "outputs"):
        old_side, new_side = old[side], new[side]
        for name in old_side.keys() - new_side.keys():
            bump("major", f"{side[:-1]} '{name}' removed")
        for name, port in new_side.items():
            if name not in old_side:
                required = isinstance(port, dict) and port.get("required", True) and side == "inputs"
                bump("major" if required else "minor", f"{'required ' if required else ''}{side[:-1]} '{name}' added")
            elif port != old_side[name]:
                bump("major", f"{side[:-1]} '{name}' changed {old_side[name]!r} -> {port!r}")
    return level, why


def _semver(v: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return a, b, c


def bump_level(old: str, new: str) -> Level | Literal["down"]:
    """Classify the version change between two ``X.Y.Z`` strings.

    Returns ``"none"`` (patch or same), ``"minor"``, ``"major"``, or ``"down"`` when the new version is lower than the old one.
    """
    o, n = _semver(old), _semver(new)
    if n < o:
        return "down"
    if n[0] > o[0]:
        return "major"
    if n[1] > o[1]:
        return "minor" if n[0] == o[0] else "major"
    return "none"


def check_pair(where: str, old: ComponentSpec | PipelineSpec, new: ComponentSpec | PipelineSpec) -> list[ContractIssue]:
    level, why = classify(contract_of(old), contract_of(new))
    got = bump_level(old.version, new.version)
    if got == "down":
        return [ContractIssue(severity="error", where=where, msg=f"version went down: {old.version} -> {new.version}")]
    if _ORDER[level] > _ORDER[got]:
        return [
            ContractIssue(
                severity="error",
                where=where,
                msg=f"contract change needs a {level} version bump (still {new.version}; was {old.version}): "
                + "; ".join(why),
                hint=f"bump `version:` in {where} ({'major' if level == 'major' else 'at least minor'})",
            )
        ]
    return []


# ------------------------------------------------------------------ git plumbing
def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def skill_paths(root: Path, rev: str | None) -> list[str]:
    """Repo-relative ``SKILL.md`` paths at ``rev`` (None = tracked and untracked files in the working tree)."""
    if rev:
        files = _git(root, "ls-tree", "-r", "--name-only", rev).splitlines()
    else:
        files = _git(root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    return sorted(f for f in files if Path(f).name == SKILL_FILE)


def _load(path: Path) -> ComponentSpec | PipelineSpec | None:
    try:
        spec = load_spec(path)
    except FabricError:
        return None  # invalid specs are reported by the drift lint, not here
    return spec if isinstance(spec, ComponentSpec | PipelineSpec) else None


def check(root: str | Path, base: str) -> list[ContractIssue]:
    """Compare every ``SKILL.md`` under ``root`` with the same file at git revision ``base``.

    Returns one `ContractIssue` per skill whose contract changed without the matching ``version:`` bump (``error``) and per removed skill
    (``notice``). Specs that do not parse are skipped; the drift lint reports them.
    """
    root = Path(root).resolve()
    issues: list[ContractIssue] = []
    head = {p: root / p for p in skill_paths(root, None) if (root / p).exists()}
    with tempfile.TemporaryDirectory() as tmp:
        for rel in skill_paths(root, base):
            if rel not in head:
                issues.append(ContractIssue(severity="notice", where=rel, msg="skill removed (breaking for its users)"))
                continue
            old_file = Path(tmp) / rel
            old_file.parent.mkdir(parents=True, exist_ok=True)
            old_file.write_text(_git(root, "show", f"{base}:{rel}"), encoding="utf-8")
            old, new = _load(old_file), _load(head[rel])
            if old and new:
                issues += check_pair(rel, old, new)
    return issues


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m agent_fabric.contracts", description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="git revision to compare against, e.g. origin/main")
    ap.add_argument("--root", default=".", help="repository root")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[\w./@^~-]+", args.base):
        ap.error("invalid --base revision")
    try:
        issues = check(args.root, args.base)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR   git failed: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    for i in issues:
        print(i)
    errors = sum(i.severity == "error" for i in issues)
    print(f"{errors} contract error(s), {len(issues) - errors} notice(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()


__all__ = [
    "ContractIssue",
    "Level",
    "bump_level",
    "check",
    "classify",
    "contract_of",
]
