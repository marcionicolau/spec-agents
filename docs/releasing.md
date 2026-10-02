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

**Release PRs stay mergeable.** All release PRs edit the shared `.release-please-manifest.json`, so merging one makes the others conflict.
The `sync-release-prs` job of `release.yml` runs `tools/release_sync.py` after every push to `main`: a release branch that no longer merges
cleanly is rebuilt as *main + the PR's own changelog/version files + only its own manifest entry*, keeps its commit message and is force-pushed with
lease using `RELEASE_PLEASE_TOKEN` (a push by `GITHUB_TOKEN` would not re-run the required checks). Mergeable branches are left alone. Locally:
`GH_TOKEN=$(gh auth token) just release-sync` (add `--dry-run` to only report).

**Distribution (GitHub Releases only).** After release-please creates a release, the `assets` job of `release.yml` checks out that tag, builds the
package (`uv build --package <pkg>`), verifies it with `tools/check_wheels.py --expect-version <version>` (skills, LICENSE, `py.typed`, exact
version without a `.dev` suffix) and attaches the wheel and sdist to the GitHub Release, using the job-scoped `GITHUB_TOKEN`: no long-lived
secret, no index. Install a release with
`uv pip install https://github.com/marcionicolau/spec-agents/releases/download/<pkg>-vX.Y.Z/<wheel file>` (or `gh release download <pkg>-vX.Y.Z --repo marcionicolau/spec-agents`).

**PyPI names and publishing.** The short names (`statistics`, `lakehouse`, `coworker`, `text-pack`) are taken on PyPI by unrelated projects, so the
distributions are published as **`spec-agents-core`** (import `agent_fabric`), **`spec-agents-statistics`** (`stat_fabric`), **`spec-agents-lakehouse`**
(`lake_fabric`), **`spec-agents-coworker`** (`coworker_fabric`) and **`spec-agents-text`** (`text_pack`). Only `[project] name` carries these names: package
directories, git tags (`agent-fabric-v0.5.0`, `statistics-v0.2.0`, ...), release-please components, PR scopes and labels keep the short names, and the
`agent-fabric` CLI and the `agent_fabric.domains` entry-point group are unchanged.

The `publish` job of `release.yml` uploads each released package's verified wheel and sdist (the artifact built by `assets`) with trusted publishing
(OIDC, no stored token, attestations on) through a **per-package environment** (`pypi-<package>`). It is **off until the repository variable `PYPI_PUBLISH` is `true`**.
PyPI accepts a given pending-publisher configuration (owner, repository, workflow, environment) for only one new project name, so the five packages cannot all use
the same environment: each has its own. One-time setup:
1. On PyPI (and TestPyPI to rehearse), add a *pending publisher* for each name (https://pypi.org/manage/account/publishing/); owner `marcionicolau`, repository
   `spec-agents`, workflow `release.yml`, and the environment of that row:

   | PyPI project | Environment |
   | --- | --- |
   | `spec-agents-core` | `pypi-agent-fabric` |
   | `spec-agents-statistics` | `pypi-statistics` |
   | `spec-agents-lakehouse` | `pypi-lakehouse` |
   | `spec-agents-coworker` | `pypi-coworker` |
   | `spec-agents-text` | `pypi-text-pack` |

   If the repository is ever renamed, update these.
2. In GitHub the five environments already exist (Settings -> Environments); optionally add yourself as a required reviewer to gate each upload.
3. Publish an existing release (retry, or a release made before PyPI was set up): Actions -> *release* -> *Run workflow* with the tag and the index, or
   `gh workflow run release.yml -f tag=statistics-v0.2.1 -f index=pypi`. It downloads that release's wheel and sdist, requires them to be `spec_agents_*`
   builds of exactly that version, and uploads them with the same per-package environment and trusted publisher (already-uploaded files are skipped, so
   it is safe to repeat). Releases made before the distribution rename carry the old names and are rejected.
4. Rehearse: set the variable `PYPI_REPOSITORY_URL` to `https://test.pypi.org/legacy/` and `PYPI_PUBLISH` to `true`, merge a release PR, check TestPyPI; then unset
   `PYPI_REPOSITORY_URL` for the real index.

The release workflow authenticates with the `RELEASE_PLEASE_TOKEN` secret (so release PRs trigger CI); rotate it by re-running
`gh secret set RELEASE_PLEASE_TOKEN`. The five packages are on PyPI (`PYPI_PUBLISH=true`; remove it to stop publishing). GitHub Releases keep the same files.

## CI
`.github/workflows/ci.yml` runs path-scoped package tests (Python 3.12/3.13), lint (ruff, actionlint), spec lint, wheel build + check
(skills, LICENSE, `py.typed`), an all-extras job (no skipped tests, coverage floor, `ty` type check) and a lowest-versions job.
Branch protection should require the single gate job **`ci-ok`** and the PR-title check **`conventional-title`**. Locally: `just check`.

## Branch protection (rulesets)
The repository is public, so two rulesets are enforced server-side:
- **`main`**: no deletion, no force-push, linear history, changes only through a pull request that is **squash-merged**, and the checks
  **`ci-ok`** and **`conventional-title`** must pass. Zero approvals are required (single maintainer); a repository admin can bypass through a
  PR when needed. Release PRs from release-please go through the same rules.
- **`release-tags`** (`*-v*`): release tags cannot be deleted, moved or updated (admins can bypass, e.g. to redo a bad release).

Other settings: squash merge only (title = PR title, which release-please reads), head branches deleted after merge, secret scanning with push
protection, Dependabot alerts and security updates, private vulnerability reporting, and workflow runs from first-time outside contributors need
approval. Default workflow permissions are read-only. `just hooks` still installs `tools/hooks/pre-push`, a local guard against pushing to
`main` by mistake. `.github/CODEOWNERS` documents ownership by area (review is not required).

Documentation is published to GitHub Pages by `.github/workflows/docs.yml` on pushes to `main`: https://marcionicolau.github.io/spec-agents/.

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
