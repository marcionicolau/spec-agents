# Security policy

## Supported versions
The project is pre-1.0. Only the **latest release of each package** receives security fixes: `agent-fabric`, `statistics`, `lakehouse`,
`coworker` and `text-pack` (see [Releases](https://github.com/marcionicolau/spec-agents/releases)). Older versions are not patched; upgrade instead.
A pack also needs a compatible core: it declares the core API level it was written for (`@requires_api`), and the loader rejects mismatches.

## Reporting a vulnerability
**Do not open a public issue, pull request or discussion for a vulnerability.** Report it privately:

1. Open a [private vulnerability report](https://github.com/marcionicolau/spec-agents/security/advisories/new) (GitHub Security Advisories).
2. Include what is affected (package, version or commit), a minimal reproduction (spec/config files, inputs, commands), the impact you see,
   and, if you have one, a suggested fix.

What to expect (this is a one-maintainer project, so these are targets, not guarantees):
- an acknowledgement within a few days and an assessment shortly after;
- a fix in the next release of the affected package, or a mitigation if a fix needs longer;
- credit in the advisory if you want it, and coordinated disclosure: please keep the report private until a fixed release is out.

There is no bug bounty.

## What is in scope
Anything that lets untrusted input break the guarantees below, in code or in the shipped specs (`SKILL.md`, `AGENT.md`):
- executing model-written or input-derived code, formulas or SQL;
- reading or writing files outside the allowed roots;
- leaking credentials into params, URLs, logs, generated files or prompts;
- bypassing the validators or budgets that bound an agent run.

Out of scope: weaknesses that need an already compromised machine, a malicious maintainer or a hostile LiteLLM/Ollama deployment; model
quality issues (wrong or unhelpful answers) that do not cross a boundary above; denial of service by providing a huge input to a local tool.
Use a normal issue for those.

## Security model (areas that deserve extra care)
- **LLMs never compute.** Results come from deterministic components; model text becomes data only in declared `runtime: prompt` outputs
  (`text`/`json`/`number`/`any`), validated and, by default, grounded against the inputs. No LLM-authored code or formula is executed
  (statistics builds formulas from validated column names).
- **Generated code** (`airflow_dag_render` / `dag_check`, lakehouse): values are `pprint`-ed into a static template, SQL identifiers are validated
  and double-quoted, row values are bound parameters, and `dag_check` rejects unsafe files (import allowlist, `eval`/`exec`/subprocess, secrets,
  destructive SQL, missing medallion tasks).
- **Filesystem** (coworker): only the working directory and the directories in `COWORKER_ALLOWED_ROOTS` can be indexed, packed, reviewed or patched;
  all paths go through `analysis.safe_path` (no absolute paths, `..` or symlink escapes); patches are applied in memory and returned as a diff, never written.
- **Credentials** live in Airflow connections (`trino_conn_id`, `auth_conn_id`), never in params, URLs or generated files.
- **Bounded runs:** depth, agent runs, delegations and LLM calls are budgeted per run.

## Supply chain and repository hardening
- `main` and release tags are protected by rulesets: pull requests only, squash merge, linear history, required checks (`ci-ok`, `conventional-title`).
- CI workflows use least-privilege `permissions`, avoid `pull_request_target`, pin every action to a commit SHA and are audited with
  `zizmor` and `actionlint`; runs from first-time outside contributors need approval.
- Secret scanning with push protection, Dependabot alerts and security updates, and private vulnerability reporting are enabled.
- Releases are built in CI from the release tag and verified before their wheel and sdist are attached to the GitHub Release; no long-lived
  publishing credentials are stored (packages are not on PyPI yet).
- Dependencies are locked (`uv.lock`) and updated through reviewed Dependabot pull requests.
