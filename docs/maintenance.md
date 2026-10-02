# Maintenance workflow

| Change                                             | Required checks                                                                                                                                                                                         |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New/changed contract (frontmatter, Params, Result) | `pytest`; bump `version` (minor = new optional field, major = breaking); `just contracts` checks it against `origin/main` and CI enforces it on PRs                                                                                                                                 |
| Body-only edit (SKILL.md/AGENT.md prose)           | `lint --strict`; `run_evals.py --mode live` — prose changes behaviour without changing code                                                                                                             |
| Model alias swap in `litellm_config.yaml`          | `run_evals.py --mode live`; compare `mean_score` with the last run                                                                                                                                      |
| Coworker scorer / `context_select` change          | `python -m coworker_fabric.evals --root .` (deterministic, labeled cases in `examples/evals/context_cases.yaml`; also asserted in `packages/coworker/tests/test_coworker.py`); add a case for every retrieval bug you fix |
| New skill / agent                                  | `scaffold` → fill sections → `lint --strict` → tests for its checks                                                                                                                                     |

## Core API level
`agent_fabric.API_LEVEL` is an integer that versions what packs build against: `Component` and its hooks, `Registry`, the `SKILL.md`
contract and artifact types, and the `register(registry)` entry point. It is independent of the package version.

- **Bump `API_LEVEL`** (in `agent_fabric/compat.py`) only for a *breaking* change of that surface; additions never bump it. In the same PR
  update every pack in the repository (`@requires_api(<new level>)`) after porting it; `tests/test_pack_api_level.py` fails otherwise.
- **Retire a level** by raising `API_LEVEL_MIN`, at least one release after announcing it, so out-of-tree packs get time to move.
- **Pack dependency ranges** stay a coarse guard (`agent-fabric>=0.0.1,<1` while pre-1.0). Widen them deliberately, and let the API
  level carry the precise compatibility: a pack for an older level keeps working until that level is retired.
- A pack that never declared a level loads unchecked; new packs must declare one.

## Public API surface
A name is public only if it is in the `__all__` of its module (and of the package `__init__` when re-exported). Internal helpers,
prompt templates, regexes and constants stay out. `tests/test_public_api.py` checks that every `__all__` name exists and is unique, that
`agent_fabric.__version__` matches the installed distribution, and that no public class/function lacks a docstring beyond the
shrinking debt list `tests/public_api_undocumented.txt`. Pack packages export `register` lazily (`stat_fabric.register`) so
`import stat_fabric` does not import pandas/scipy. Changing what is exported is an API change: breaking removals follow the
pre-1.0 rule (minor bump) and are noted in the PR title scope.

## Eval baselines
`examples/evals/baselines.json` stores the scores of the deterministic suites: the statistics rules planner (per case and mean;
`treatment_effect` fails on purpose) and coworker context selection (means). The context suite indexes only `packages/**/*.py` and `tests/**/*.py` (`REPO_EVAL_INCLUDE`): its labelled cases refer to those files, and new files elsewhere (docs/, tools/, examples/) that merely share vocabulary with a task would otherwise change the score for unrelated reasons. `just evals-check` (CI, `specs` job) fails when a
score drops below `baseline - tolerance` (0.02), or when a case is added or removed without refreshing the file. To refresh after
an intended change run `just evals-update` and commit the diff in the same PR, so the new baseline is reviewed. Scores above
baseline + tolerance are reported as improvements: refresh them too, so the gain is protected.

Live LLM evals (`just evals live`, needs the LiteLLM proxy) are manual. PRs that change SKILL.md/AGENT.md/fabric.md prose or the
model aliases are labelled `stage:needs-eval` automatically: run them, paste `mean_score` next to the previous one in the PR,
then remove the label.

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
