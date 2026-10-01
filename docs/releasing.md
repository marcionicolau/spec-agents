# Releasing, versions and issue workflow

## Versions come from git tags
No `pyproject.toml` has a `version`. `uv-dynamic-versioning` (hatchling build backend) reads the latest `<package>-vX.Y.Z` tag of
that package (`pattern-prefix = "<package>-"`; other packages' tags are ignored):

| Commit                         | Version of the package                |
| ------------------------------ | ------------------------------------- |
| tagged `coworker-v0.1.0`       | `0.1.0`                               |
| N commits after that tag       | `0.1.1.devN+<sha>`                    |
| no tag (shallow clone)         | `0.0.0` (fallback) — fetch tags/history |

`uv.lock` therefore never pins workspace versions. CI checkouts use `fetch-depth: 0`. Never create or move `<package>-v*` tags by hand.

## Release flow (release-please)
1. Merge PRs with conventional titles and a package scope: `feat(statistics): …`, `fix(agent-fabric): …`. Squash merge, so the title is the commit.
2. release-please keeps one release PR per package (`release-please-config.json`, `.release-please-manifest.json`, `release-type: simple`),
   with the next version and `packages/<pkg>/CHANGELOG.md`. Pre-1.0: breaking changes bump the minor, features the patch.
3. Merging a release PR creates the `<package>-vX.Y.Z` tag and a GitHub Release; that tag is what the build reads.
4. Paths outside `packages/<pkg>/` never trigger a release; cross-cutting changes use `chore`, `ci`, `docs`, `deps`.
5. `SKILL.md` `version:` fields are contracts, not releases: bump them by hand (minor = new optional field, major = breaking).

The release workflow authenticates with the `RELEASE_PLEASE_TOKEN` secret (so release PRs trigger CI); rotate it by re-running
`gh secret set RELEASE_PLEASE_TOKEN`. Packages are not published to an index yet.

## CI
`.github/workflows/ci.yml` runs path-scoped package tests (Python 3.12/3.13), lint (ruff, actionlint), spec lint, wheel build + check
(skills, LICENSE, `py.typed`), an all-extras job (no skipped tests, coverage floor, `ty` type check) and a lowest-versions job.
Branch protection should require the single gate job **`ci-ok`** and the PR-title check **`conventional-title`**. Locally: `just check`.

## Branch protection (free plan, private repo)
GitHub rulesets and branch protection need a public repo or GitHub Pro, so nothing is enforced server-side. What is in place instead:
- Repository merge settings: squash merge only (title = PR title, which release-please reads), head branches deleted after merge.
- `just hooks` installs `tools/hooks/pre-push`, which refuses direct pushes to `main` (`ALLOW_MAIN_PUSH=1` to override on purpose).
- Merge from the CLI after checking the gate: `gh pr checks <n>` must show `ci-ok` and `conventional-title` passing, then `gh pr merge <n> --squash`.
- `.github/CODEOWNERS` documents who owns which area; it becomes enforceable if the repo goes public or to Pro
  (then add a ruleset requiring `ci-ok` + `conventional-title`, linear history, no force-push, and Code Owner review).

## Workflow hardening
Every `uses:` is pinned to a commit SHA with the tag in a trailing comment; dependabot (weekly, 7-day cooldown) bumps both. `zizmor` and
`actionlint` run in the lint job; tools installed by actions (`uv`, `just`) are pinned by version. Workflows use least-privilege
`permissions` per job and avoid `pull_request_target`.

## Issues and labels
Every issue gets a `pkg:*` label (package or area), one `stage:*` label and a type (`bug`, `enhancement`, `documentation`, `type:*`);
issue forms apply `pkg:` and `stage:triage`, PRs get `pkg:` labels from the files they touch. Labels are defined in `.github/labels.yml`.

| Stage label          | Meaning                                                  |
| -------------------- | -------------------------------------------------------- |
| `stage:triage`       | new, not looked at                                       |
| `stage:needs-design` | a decision is needed before work starts                  |
| `stage:ready`        | clear enough to pick up                                  |
| `stage:in-progress`  | being worked on                                          |
| `stage:blocked`      | waiting on another item                                  |
| `stage:needs-review` | PR open, awaiting review                                 |
| `stage:needs-eval`   | guidance/model change awaiting `run_evals.py --mode live` |
| `stage:released`     | shipped in a release                                     |
