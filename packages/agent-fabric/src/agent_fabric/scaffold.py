"""Scaffold new SKILL.md / AGENT.md files - or a whole domain pack - with the canonical sections (keeps packs uniform).

python -m agent_fabric.scaffold skill   my_step   --dir src/my_pack/skills --domain my_domain
python -m agent_fabric.scaffold pipeline my_flow  --dir src/my_pack/skills --domain my_domain
python -m agent_fabric.scaffold agent   reviewer  --dir config --kind llm
python -m agent_fabric.scaffold pack    my-pack   [--dir packages]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL = """---
name: {name}
version: 0.1.0
domain: {domain}
category: other
description: TODO one line - what it does (shown in every planner catalogue, keep < 200 chars).
runtime: code               # or 'prompt' - 'scaffold prompt' gives the code-free variant
params:
  example_param: {{description: TODO, example: null}}
inputs:
  data: {{type: dataframe, description: TODO, constraints: {{min_rows: 1}}}}
outputs: {{}}
---
# {title}

## When to use
TODO - first paragraph goes to the planner catalogue; be concrete (which questions, which data).

## When not to use
TODO - and what to use instead.

## Interpreting
TODO - how to read the Result fields (use `backticks` only for real field/param names).

## Common mistakes
TODO - parameter mistakes the repairer and planner should avoid.
"""

PROMPT = """---
name: {name}
version: 0.1.0
domain: {domain}
category: other
description: TODO one line - what it does (shown in every planner catalogue, keep < 200 chars).
runtime: prompt
prompt: {{grounding: true}}           # optional: model, temperature, grounding
params:
  tone: {{description: TODO, required: false, default: neutral}}
inputs:
  source: {{type: text, description: TODO, constraints: {{min_chars: 1}}}}
outputs:
  answer: {{type: text}}
---
# {title}

## When to use
TODO - first paragraph goes to the planner catalogue; be concrete.

## Instructions
TODO - the prompt template sent to the model. Placeholders: {{params.<name>}},
{{inputs.<port>}} and {{objective}}. Escape literal braces as {{{{ }}}}.

Work for a {{params.tone}} audience.

{{inputs.source}}

## Interpreting
TODO - how to read `answer` / the Result.

## Common mistakes
TODO - what the repairer and planner should avoid.
"""

PIPELINE = """---
name: {name}
kind: pipeline
version: 0.1.0
domain: {domain}
description: TODO one line.
params:
  example_param: {{description: TODO, required: true}}
inputs:
  data: {{type: dataframe, description: TODO}}
steps:
  - {{id: summary, component: summary}}
outputs: {{}}
---
# {title}

## When to use
TODO

## Procedure
1. TODO - why each step, in this order.

## Interpreting
TODO
"""

AGENT = """---
name: {name}
kind: {kind}
role: TODO role
description: TODO one line - what parents see when deciding to delegate here.
{extra}---
TODO - working instructions (this body is the agent's system prompt).
Mention sub-agents / components with `backticks` so the lint can check them.
"""

_EXTRA = {
    "supervisor": "strategy: router\nsub_agents: []\n",
    "planner": "domains: []\n",
    "pipeline": "pipeline: TODO\n",
    "function": "function: TODO\n",
    "llm": "",
}

# ---------------------------------------------------------------------- pack scaffolding (packages/<name>)

PACK_PYPROJECT = """\
[project]
name = "{dist}"
dynamic = ["version"]
description = "TODO - {domain} domain pack for agent-fabric"
requires-python = ">=3.12"
license = "MIT"
license-files = ["LICENSE"]
readme = "README.md"
keywords = ["agents", "{domain}"]
classifiers = [
  "Development Status :: 2 - Pre-Alpha",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3 :: Only",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Typing :: Typed",
]
dependencies = [
  "spec-agents-core>=0.0.1,<1",
]

[project.entry-points."agent_fabric.domains"]
{domain} = "{module}:register"

[project.urls]
Homepage = "https://github.com/marcionicolau/spec-agents"
Repository = "https://github.com/marcionicolau/spec-agents"
Issues = "https://github.com/marcionicolau/spec-agents/issues"
Documentation = "https://github.com/marcionicolau/spec-agents/tree/main/docs"

[build-system]
requires = ["hatchling", "uv-dynamic-versioning>=0.14"]
build-backend = "hatchling.build"

[tool.uv]
package = true

[tool.uv.sources]
spec-agents-core = {{ workspace = true }}

# version = latest "{name}-vX.Y.Z" git tag (other packages' tags are ignored); untagged commits get X.Y.(Z+1).devN+<sha>
[tool.hatch.version]
source = "uv-dynamic-versioning"

[tool.hatch.build.targets.wheel]
packages = ["src/{module}"]

[tool.uv-dynamic-versioning]
vcs = "git"
style = "pep440"
bump = true
pattern-prefix = "{name}-"
fallback-version = "0.0.0"
"""

PACK_INIT = """\
\"\"\"{title} domain pack for agent-fabric.

Component: `echo` - a minimal sample, replace it with real components.
Load with ``build_registry([{module}.register])`` or the ``agent_fabric.domains`` entry point.
\"\"\"

from __future__ import annotations

from pathlib import Path

from agent_fabric.compat import requires_api
from agent_fabric.component import Component, ComponentParams, ComponentResult, StepContext
from agent_fabric.registry import Registry, component

SPEC_DIR = Path(__file__).parent / "skills"


class EchoParams(ComponentParams):
    \"\"\"Parameters of `echo`.\"\"\"

    uppercase: bool = False


class EchoResult(ComponentResult):
    \"\"\"Result of `echo`.\"\"\"

    text: str
    n_chars: int


@component("echo")
class Echo(Component[EchoParams, EchoResult]):
    \"\"\"Return the input text, optionally upper-cased. A placeholder component - replace it.\"\"\"

    Params = EchoParams
    Result = EchoResult

    def compute(self, inputs: dict, params: EchoParams, ctx: StepContext) -> EchoResult:
        \"\"\"Echo the `text` input, upper-cased when `uppercase` is set.\"\"\"
        text = inputs["text"]
        return EchoResult(text=text.upper() if params.uppercase else text, n_chars=len(text))

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        \"\"\"One-line summary of the echo result.\"\"\"
        return f"Echoed {{r['n_chars']}} characters.", []


@requires_api(1)
def register(registry: Registry) -> list[str]:
    \"\"\"Register the `{domain}` domain (the `echo` component); returns the names registered.\"\"\"
    return registry.load_domain(SPEC_DIR, [Echo])


__all__ = [
    "SPEC_DIR",
    "Echo",
    "EchoParams",
    "EchoResult",
    "register",
]
"""

PACK_SKILL = """\
---
name: echo
version: 0.1.0
domain: {domain}
category: other
description: Returns the input text, optionally upper-cased. Sample component - replace it.
runtime: code
params:
  uppercase: {{description: upper-case the text, example: true}}
inputs:
  text: {{type: text, description: input text, constraints: {{min_chars: 1}}}}
outputs: {{}}
---
# Echo

## When to use
Sample component generated by `python -m agent_fabric.scaffold pack`. Replace it with a real one
(`scaffold skill <name> --dir src/{module}/skills --domain {domain}`) and fill in the TODO sections.

## Interpreting
`text` is the (possibly upper-cased) input; `n_chars` its length.
"""

PACK_TEST = """\
\"\"\"{title} pack on its own.\"\"\"

{imports}


def test_registers_echo():
    reg = build_registry([register])
    assert "echo" in reg.names()


def test_echo_uppercases():
    res, _ = run_component(build_registry([register]), "echo", {{"uppercase": True}}, text="hello")
    assert res.text == "HELLO" and res.n_chars == 5
"""

PACK_README = """\
# {dist} (`{module}`)

{title} domain pack for [agent-fabric](../agent-fabric/README.md). Component: `echo` (sample - replace it).

## Names

| | |
| --- | --- |
| PyPI distribution | `{dist}` |
| Import name | `{module}` |
| Directory in the monorepo | `packages/{name}` |
| Release tag / PR scope | `{name}-vX.Y.Z` / `{name}` |

## Install

```bash
pip install {dist}
```

```python
from agent_fabric import build_registry
from {module} import register

registry = build_registry([register])
```

Add skills with `python -m agent_fabric.scaffold skill <name> --dir src/{module}/skills --domain {domain}`
(or `scaffold prompt` for a code-free `runtime: prompt` skill); see docs/extending.md.
"""

_PACK_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def _insert_before(path: Path, anchor: str, text: str, notes: list[str]) -> None:
    """Insert ``text`` before the first ``anchor`` occurrence; record a note when the anchor is gone."""
    src = path.read_text(encoding="utf-8")
    if anchor not in src:
        notes.append(f"edit {path.name} by hand: anchor {anchor.strip()!r} not found")
        return
    path.write_text(src.replace(anchor, text + anchor, 1), encoding="utf-8")


def _link_pack(root: Path, name: str, module: str, domain: str, notes: list[str]) -> None:
    """Wire a new pack into the repo-level files (release-please, labels, isort, justfile, docs)."""
    cfg, manifest = root / "release-please-config.json", root / ".release-please-manifest.json"
    if not cfg.exists():
        notes.append(f"no release-please-config.json at {root} - repo wiring skipped")
        return
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["packages"][f"packages/{name}"] = {"release-type": "simple", "package-name": name, "component": name}
    cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if manifest.exists():
        vers = json.loads(manifest.read_text(encoding="utf-8"))
        vers[f"packages/{name}"] = "0.0.1"
        manifest.write_text(json.dumps(vers, indent=2) + "\n", encoding="utf-8")

    labeler, labels = root / ".github/labeler.yml", root / ".github/labels.yml"
    if labeler.exists():
        _insert_before(
            labeler,
            '"pkg:specs":',
            f'"pkg:{name}":\n  - changed-files:\n      - any-glob-to-any-file: ["packages/{name}/**"]\n',
            notes,
        )
    if labels.exists():
        _insert_before(
            labels,
            '- name: "pkg:specs"',
            f'- name: "pkg:{name}"\n  color: "1d76db"\n  description: "Package {name}"\n',
            notes,
        )

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        src = pyproject.read_text(encoding="utf-8")
        m = re.search(r"known-first-party = \[([^\]]*)\]", src)
        if m and f'"{module}"' not in m.group(1):
            pyproject.write_text(src[: m.end(1)] + f', "{module}"' + src[m.end(1) :], encoding="utf-8")
        elif not m:
            notes.append("edit pyproject.toml by hand: known-first-party not found")

    api_test = root / "tests/test_public_api.py"
    if api_test.exists():
        src = api_test.read_text(encoding="utf-8")
        m = re.search(r"PACKAGES = \[([^\]]*)\]", src)
        if m and f'"{module}"' not in m.group(1):
            api_test.write_text(src[: m.end(1)] + f', "{module}"' + src[m.end(1) :], encoding="utf-8")

    justfile = root / "justfile"
    if justfile.exists():
        src = justfile.read_text(encoding="utf-8")
        m = re.search(r'^packages := "([^"]*)"', src, re.M)
        if m and name not in m.group(1).split():
            justfile.write_text(src[: m.end(1)] + f" {name}" + src[m.end(1) :], encoding="utf-8")
        _insert_before(
            justfile,
            "    uv run agent-fabric catalog",
            f"    uv run python -m agent_fabric.lint --strict --domains {module}:register\n",
            notes,
        )

    packs_doc = root / "docs/packs.md"
    if packs_doc.exists():
        _insert_before(
            packs_doc,
            "\n- **statistics**:",
            f"| `{name}` | `{module}` | `echo` | - | - |\n",
            notes,
        )
        _insert_before(packs_doc, "- **notes**", f"- **{name}**: TODO describe the pack.\n", notes)

    gen_ref = root / "docs/gen_reference.py"
    if gen_ref.exists():
        src = gen_ref.read_text(encoding="utf-8")
        if f'"{name}":' not in src:
            m = re.search(r"PYPI_NAMES = \{[^}]*\n\}", src)
            if m:
                src = src.replace(
                    m.group(0), m.group(0)[:-1] + f'    "{name}": "spec-agents-{name.removesuffix("-pack")}",\n}}', 1
                )
            m = re.search(r'"text-pack": \("[^"]*", "[^"]*"\),\n\}', src)
            if m:
                src = src.replace(
                    m.group(0),
                    m.group(0)[:-1] + f'    "{name}": ("{module}", "TODO - {domain} domain pack."),\n}}',
                    1,
                )
            gen_ref.write_text(src, encoding="utf-8")


def scaffold_pack(
    name: str,
    packages_dir: str | Path = "packages",
    *,
    domain: str | None = None,
    module: str | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Create a whole domain pack at ``<packages_dir>/<name>`` (text-pack layout) and wire it into the repo.

    ``name`` is the kebab-case directory / release-please component / tag prefix (``my-pack-v0.1.0``); a
    trailing ``-pack`` is dropped from the PyPI name (``spec-agents-my``) and default ``domain``. The import
    module defaults to ``name`` with dashes as underscores (``_pack`` appended on a stdlib collision) and may
    be overridden with ``module``. Returns the pack directory; ``notes`` collects follow-ups for files the
    scaffold could not update itself.
    """
    notes = notes if notes is not None else []
    if not _PACK_NAME.match(name):
        raise ValueError(f"pack name must be kebab-case: {name!r}")
    module = module or name.replace("-", "_")
    if not re.match(r"^[a-z][a-z0-9_]{0,39}$", module):
        raise ValueError(f"module name must be snake_case: {module!r}")
    if module in sys.stdlib_module_names:
        module += "_pack"
    domain = domain or name.removesuffix("-pack")
    dist = f"spec-agents-{domain.replace('_', '-')}"
    pack = Path(packages_dir) / name
    if pack.exists():
        raise FileExistsError(pack)

    title = domain.replace("_", " ").replace("-", " ").capitalize()
    imports = "\n".join(
        f"from {mod} import {what}"
        for mod, what in sorted(
            [("agent_fabric", "build_registry"), ("agent_fabric.testing", "run_component"), (module, "register")]
        )
    )
    fmt = dict(name=name, module=module, domain=domain, dist=dist, title=title, imports=imports)
    files = {
        "pyproject.toml": PACK_PYPROJECT.format(**fmt),
        "README.md": PACK_README.format(**fmt),
        f"src/{module}/__init__.py": PACK_INIT.format(**fmt),
        f"src/{module}/py.typed": "",
        f"src/{module}/skills/echo/SKILL.md": PACK_SKILL.format(**fmt),
        f"tests/test_{module}.py": PACK_TEST.format(**fmt),
    }
    license_src = Path(packages_dir).parent / "LICENSE"
    if license_src.exists():
        files["LICENSE"] = license_src.read_text(encoding="utf-8")
    else:
        notes.append("LICENSE not found at the repo root - copy one into the pack")
    for rel, text in files.items():
        path = pack / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    _link_pack(Path(packages_dir).resolve().parent, name, module, domain, notes)
    return pack


def scaffold(what: str, name: str, directory: str | Path, domain: str = "core", kind: str = "llm") -> Path:
    """Create a spec skeleton with the canonical sections and return its path.

    ``what`` is ``"skill"``, ``"prompt"``, ``"pipeline"`` or ``"agent"``; ``name`` must be snake_case. Writes ``<directory>/<name>/SKILL.md`` (or
    ``<directory>/agents/<name>/AGENT.md``).
    """
    if not re.match(r"^[a-z][a-z0-9_]{0,39}$", name):
        raise ValueError(f"name must be snake_case: {name!r}")
    title = name.replace("_", " ").capitalize()
    if what == "agent":
        path = Path(directory) / "agents" / name / "AGENT.md"
        text = AGENT.format(name=name, kind=kind, extra=_EXTRA.get(kind, ""))
    else:
        path = Path(directory) / name / "SKILL.md"
        tpl = {"pipeline": PIPELINE, "prompt": PROMPT}.get(what, SKILL)
        text = tpl.format(name=name, domain=domain, title=title)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m agent_fabric.scaffold")
    ap.add_argument("what", choices=["skill", "pipeline", "prompt", "agent", "pack"])
    ap.add_argument("name")
    ap.add_argument("--dir", help="spec/agent directory; for 'pack': the packages root (default: packages)")
    ap.add_argument("--domain", help="domain name; default: 'core', for 'pack': <name> minus a -pack suffix")
    ap.add_argument("--module", help="pack only: import module name (default: <name> with dashes as underscores)")
    ap.add_argument("--kind", default="llm", choices=sorted(_EXTRA))
    a = ap.parse_args(argv)
    notes: list[str] = []
    try:
        if a.what == "pack":
            print(scaffold_pack(a.name, a.dir or "packages", domain=a.domain, module=a.module, notes=notes))
            print("next: uv sync --all-packages && just check")
        else:
            if not a.dir:
                raise ValueError("--dir is required")
            print(scaffold(a.what, a.name, a.dir, a.domain or "core", a.kind))
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()


__all__ = [
    "scaffold",
    "scaffold_pack",
]
