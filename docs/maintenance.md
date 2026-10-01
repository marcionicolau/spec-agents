# Maintenance workflow

| Change                                             | Required checks                                                                                                                                                                                         |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New/changed contract (frontmatter, Params, Result) | `pytest`; bump `version` (minor = new optional field, major = breaking); `just contracts` checks it against `origin/main` and CI enforces it on PRs                                                                                                                                 |
| Body-only edit (SKILL.md/AGENT.md prose)           | `lint --strict`; `run_evals.py --mode live` — prose changes behaviour without changing code                                                                                                             |
| Model alias swap in `litellm_config.yaml`          | `run_evals.py --mode live`; compare `mean_score` with the last run                                                                                                                                      |
| Coworker scorer / `context_select` change          | `python -m coworker_fabric.evals --root .` (deterministic, labeled cases in `examples/evals/context_cases.yaml`; also asserted in `packages/coworker/tests/test_coworker.py`); add a case for every retrieval bug you fix |
| New skill / agent                                  | `scaffold` → fill sections → `lint --strict` → tests for its checks                                                                                                                                     |

Lint rules (`agent_fabric/lint.py`): unknown backticked identifiers, missing canonical sections, broken
relative links (error), description > 200 or < 20 chars, description style (`description_filler`: not "This component…"/"A…"; `description_first_person`; `description_no_trigger`: neither the description nor the first paragraph of `## When to use` says when it applies; `description_duplicate`: two skills with the same text), skill body > 6000 / agent body > 4000 chars, router bodies
that never mention a sub-agent, bodies mentioning agents that are not sub-agents, plus full tree validation.
Evals (`agent_fabric/evals.py`): cases name expected/forbidden components; score = 0.7 valid + 0.1 first try

- 0.2 coverage − 0.3 per forbidden component (same score as the DSPy metric). The rules baseline
  intentionally fails `treatment_effect` (it is objective-blind) — that is what an LLM planner should beat.

Single source of truth: never duplicate a contract in YAML _and_ SKILL.md for the same name (the loader
rejects duplicate names). Keep YAML only for legacy packs.

## Lakehouse and coworker packs (rules specific to them)

- **Generated code is never trusted twice.** `airflow_dag_render` interpolates only `pprint`-ed validated values into a
  static template (no value reaches code or SQL text; SQL identifiers pass `IDENT` and are double-quoted; row values are
  bound parameters). `dag_check` then rejects the file (imports allowlist, eval/exec/subprocess, secrets, destructive SQL,
  missing medallion tasks). Tests execute the generated DAG against stubbed Airflow/Trino modules.
- **Sources never load partially by accident**: API pagination (`next_link` on the same host only, `cursor`, `page`) fails the
  run when `max_pages` is exhausted; incremental loads (`watermark_column`) read the max value from silver, keep records `>=` it,
  and require `load_mode: merge`. An empty increment passes the gate; an empty non-incremental source fails it.
- **Credentials live in Airflow connections** (`trino_conn_id`, `auth_conn_id`), never in params, URLs or generated files.
- **Context selection is measured, not guessed.** `Scorer` (analysis.py) is BM25-flavoured: IDF over the indexed files, path matches x3,
  symbol-name matches x2, tests down-weighted unless asked for, `relative_cutoff` drops weak candidates, and files over a quarter of the
  budget contribute only their matching symbols (`ranges`). The index stores stemmed vocabularies (`terms`) per file and symbol.
- **Coworker never writes to disk.** `patch_propose` applies edits in memory, restricts them to the selected context,
  and returns a unified diff. All paths go through `analysis.safe_path` (no absolute paths, `..` or symlink escapes).
- **Coworker roots are allowlisted**: only the working directory, or the directories in `COWORKER_ALLOWED_ROOTS`
  (os.pathsep-separated), can be indexed, packed, reviewed or patched (`root_not_allowed`). Tests set the variable to `tmp_path`.
- Flow-style YAML in SKILL.md (`{description: ..., example: ...}`): quote any description containing `,` or `:`.
