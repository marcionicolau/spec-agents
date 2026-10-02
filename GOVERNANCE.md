# Governance

A small, maintainer-led project. This page says who decides what and how work flows, so contributors know what to expect.

## Roles
- **Maintainer** ([@marcionicolau](https://github.com/marcionicolau)): sets direction, triages, reviews, merges and releases. Owns every area in
  [`.github/CODEOWNERS`](.github/CODEOWNERS).
- **Contributors**: anyone who opens an issue, a pull request or a review. No sign-up or CLA; contributions are under the project's
  [MIT license](LICENSE).
- New maintainers (or area owners per package) are added by the maintainer after sustained, good contributions.

## How decisions are made
- Small changes: a reviewed pull request is enough.
- Changes to a **contract** (spec formats, `Component` hooks, `Registry`, artifact types, the pack API level) or to the **principles** in
  the [roadmap](ROADMAP.md): open an issue first and agree on the design there (`stage:needs-design`); breaking changes follow the policy in
  [docs/maintenance.md](docs/maintenance.md#core-api-level).
- Disagreements are settled in the issue by the maintainer after discussion, with the reasoning written down.

## Triage and planning
Every issue has a `pkg:*` label (area), one `stage:*` label and a type (`bug`, `enhancement`, `documentation`, `type:*`); the project board's
*Status* follows the same flow.

| Stage / Status | Meaning |
| --- | --- |
| Triage (`stage:triage`) | New; the maintainer replies, labels and decides within a few days |
| `stage:needs-design` | Needs a decision before work starts |
| Backlog | Accepted, not scheduled |
| Ready (`stage:ready`) | Clear enough to pick up |
| In progress (`stage:in-progress`) | Being worked on; one assignee |
| In review (`stage:needs-review`) | Pull request open |
| Done | Merged and closed (`stage:released` once shipped) |

Items are scheduled into a [milestone](ROADMAP.md#milestones) (a theme) and prioritised with `prio:*`. `stage:blocked` marks work waiting on
something else, with the blocker named in the issue.

## Pull requests and releases
- Pull requests need green `ci-ok` and `conventional-title`, a conventional title with a package scope, and are squash-merged
  ([CONTRIBUTING.md](CONTRIBUTING.md)). Review is requested from the owners but approval is not mandatory while there is one maintainer.
- Releases are automatic per package: merging a release-please PR tags the package and attaches its wheel and sdist to the GitHub Release
  ([docs/releasing.md](docs/releasing.md)). There is no fixed calendar; a release happens when a release PR is merged.
- Security reports follow [SECURITY.md](SECURITY.md); conduct reports follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Changing this document
By pull request, like everything else.
