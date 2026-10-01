"""Scaffold new SKILL.md / AGENT.md files with the canonical sections (keeps packs uniform).

python -m agent_fabric.scaffold skill   my_step   --dir src/my_pack/skills --domain my_domain
python -m agent_fabric.scaffold pipeline my_flow  --dir src/my_pack/skills --domain my_domain
python -m agent_fabric.scaffold agent   reviewer  --dir config --kind llm
"""

from __future__ import annotations

import argparse
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


def scaffold(what: str, name: str, directory: str | Path, domain: str = "core", kind: str = "llm") -> Path:
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
    ap.add_argument("what", choices=["skill", "pipeline", "prompt", "agent"])
    ap.add_argument("name")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--domain", default="core")
    ap.add_argument("--kind", default="llm", choices=sorted(_EXTRA))
    a = ap.parse_args(argv)
    try:
        print(scaffold(a.what, a.name, a.dir, a.domain, a.kind))
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
