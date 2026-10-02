# Extending: components, prompt components, pipelines

> **Format note.** `SKILL.md` here is a _superset_ of the open [Agent Skills](https://agentskills.io/specification) format: the
> frontmatter carries the executable contract (`params`, `inputs`, `outputs`, `steps`, `runtime`, ...) and names are snake_case.
> The reference validator accepts only `name`, `description`, `license`, `compatibility`, `metadata` (string values) and
> `allowed-tools`, with kebab-case names, so fabric skills are not loadable as-is by other agents. `agent-fabric export-skills --out DIR`
> (`just skills-export`) writes a spec-compliant _view_ of every skill (kebab-case name, description + when to use, string metadata,
> guidance body plus a generated `## Contract` section, `references/` copied) and validates it; CI runs it on every PR. The fabric
> `SKILL.md` stays the single source of truth; nothing is read back from the export.

## Declaring the core API level (every pack)

A pack states which core API it was written for by decorating its `register` function:

```python
from agent_fabric import requires_api


@requires_api(1)
def register(registry): ...
```

`build_registry` and the `agent_fabric.domains` entry-point discovery refuse a pack that needs a newer level than the core implements
(`API_LEVEL`) or targets a retired one (below `API_LEVEL_MIN`) with a located `SpecError` (`pack_needs_newer_core`, `pack_api_retired`).
A pack without the decorator still loads, unchecked. Policy: [maintenance](maintenance.md#core-api-level).

## Starting a new pack

```bash
python -m agent_fabric.scaffold pack my-pack          # -> packages/my-pack/ (run from the repo root)
uv sync --all-packages && just check                 # the scaffolded pack passes CI as-is
```

The pack name is the directory / release-please component / tag prefix (`my-pack-v0.1.0`); a trailing `-pack`
is dropped from the PyPI name (`spec-agents-my`) and the default `domain`. `--module` overrides the import
module (default `my_pack`; a `_pack` suffix is added automatically on a stdlib collision like `statistics`),
`--dir` the packages root (default `packages`), `--domain` the domain name.

Generated: `pyproject.toml` (dynamic version, `spec-agents-core>=0.0.1,<1`, `agent_fabric.domains` entry
point), `src/<module>/` with `register()` decorated `@requires_api(1)`, `py.typed`, a working `echo` sample
component with its `SKILL.md`, a passing `tests/` file, `README.md` and `LICENSE`. Inside this repo the
command also wires `release-please-config.json` + `.release-please-manifest.json`, the `pkg:<name>` entries
in `.github/labeler.yml` + `.github/labels.yml`, `known-first-party` in the root `pyproject.toml`,
`tests/test_public_api.py`, the `justfile` (`packages` list and a lint line in `specs`), `docs/packs.md` and
`docs/gen_reference.py`. Outside the repo layout it prints the wiring to do by hand instead.

## Adding a component (any domain)

1. **Skill** `<pack>/skills/<name>/SKILL.md`, where `<pack>` = `packages/<domain>/src/<module>`
   (start from `python -m agent_fabric.scaffold skill <name> ...`):

   ```markdown
   ---
   name: my_step # snake_case, unique, == folder name
   version: 1.0.0
   domain: my_domain # catalogue filter for planners
   description: One line, < 200 chars (sent in every planner catalogue)
   runtime: code # 'prompt' = no Python class, see the prompt-runtime section below
   params: # one entry per Params field (contract-checked)
     top_k: { description: "...", example: 5 }
   inputs: # typed ports; constraints validated by the artifact type
     data: { type: dataframe, constraints: { min_rows: 10, roles: [...] } }
   outputs: # extra outputs; 'result' (the JSON Result) is implicit
     scores: { type: dataframe }
   ---

   # My step

   ## When to use -> planner catalogue (first paragraph only)

   ## When not to use -> planner catalogue (first paragraph only)

   ## Interpreting -> step interpreter prompt (≤ 1500 chars)

   ## Common mistakes -> parameter repair + planner feedback when a plan using it is rejected
   ```

   Put long material in `skills/<name>/references/*.md` and link it; it is read only via
   `Guidance.reference(...)` / `registry.guidance(...)`, never injected automatically.
   Use `backticks` only for real identifiers (params, ports, Result fields, component names): the lint checks them.

2. **Class**:
   ```python
   @component("my_step")
   class MyStep(Component[MyParams, MyResult]):        # stats: TableComponent (port 'data')
       Params, Result = MyParams, MyResult             # ComponentParams / ComponentResult subclasses; floats as Num
       def compute(self, inputs, params, ctx): ...     # ctx.emit("scores", df) for declared outputs
       def extra_checks(self, inputs, params): ...     # runtime, return list[ErrorDetail]
       def extra_static(self, bound, params): ...      # plan time; bound = {port: profile|None}
       def summarize(self, result) -> (headline, findings)   # rule-based interpretation
   ```
3. **Register** via the pack's `register(registry)` → `registry.load_domain(SPEC_DIR, classes)`.
4. **Test**: happy path; each check yields the expected `(loc, type)`; plan-level validation; JSON-serialisable result.
5. Do **not** touch planners, prompts, executor or registry — the catalogue is generated from specs.

New artifact type: subclass `ArtifactType` (`accepts`, `profile`, `Constraints`, `static_check`,
`runtime_check`) and `registry.types.register(...)` in the pack's `register`.

Registration fails on: spec/Params mismatch, unknown port type, invalid port constraints, spec without
implementation. Runtime: emitting an undeclared output or the wrong type raises `SpecError`.

### Prompt components — `runtime: prompt` (no Python)

A SKILL.md can be the entire component: `runtime: prompt` skips the class and `register()` call —
`Registry.load_domain` binds it to `PromptComponent`, which builds Params dynamically from the spec.
The prompt template is the `## Instructions` body section; placeholders `{params.<name>}`,
`{inputs.<port>}` and `{objective}` are validated against the declared contract at registration
(`unknown_placeholder`), missing Instructions is `missing_instructions`, literal braces escape as `{{ }}`.
Outputs must be `text`/`json`/`number`/`any` (`prompt_output_type`) — a prompt step can never feed a
`dataframe` port, so the deterministic-compute boundary holds for typed data. With declared outputs the
model must answer a JSON object (validated, self-corrected, grounded by default — set
`prompt: {grounding: false}` to opt out); with no outputs, free text is taken verbatim. Prompt steps run
inside pipelines and through planner agents; the LLM backend and objective arrive via `StepContext`
(`llm`, `llm_settings`, `objective`) and every call is charged to `budget.max_llm_calls`. No-LLM runs fail
the step as `dependency`. Scaffold: `python -m agent_fabric.scaffold prompt <name> --dir ... --domain ...`.
See `examples/notes/` for a domain that is 100% Markdown.

---

## Adding a pipeline (spec only, no code)

`skills/<name>/SKILL.md` with `kind: pipeline`:

```markdown
---
name: my_pipeline
kind: pipeline
version: 1.0.0
domain: my_domain
description: One line.
params:
  {
    features: { description: ..., required: true },
    k: { description: ..., default: null },
  }
inputs: { data: { type: dataframe } }
steps:
  - { id: pca, component: pca, params: { features: $params.features } }
  - {
      id: clusters,
      component: clustering,
      params: { k: $params.k },
      inputs: { matrix: pca.scores },
    }
outputs: { labels: clusters.labels }
---

# My pipeline

## When to use

## Procedure (why these steps, in this order - required by the lint)
```

References: `$inputs.<name>`, `<step>.<port>` (`result` always exists), `$params.<name>` (templates only;
a `$params` value resolving to `null` is dropped so the component default applies). Unbound ports
auto-bind to a same-named pipeline input, or — if required — to the only type-compatible input.
Registered pipelines are components: they can be steps of other pipelines (nesting depth ≤ 8) and
targets of `kind: pipeline` agents. Invalid references are reported at registration with suggestions.

---
