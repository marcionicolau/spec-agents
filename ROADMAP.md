# Roadmap

What the project is aiming at and how work is planned. The live view is the
[project board](https://github.com/users/marcionicolau/projects/14); the plan below is the stable summary. Milestones are **themed
releases of the whole repository**, not version numbers of one package: the five packages version independently (see
[docs/releasing.md](docs/releasing.md)), and a milestone says which theme a change belongs to.

## Where the project is
`agent-fabric` 0.5 and four domain packs (`statistics`, `lakehouse`, `coworker`, `text-pack`) work end to end: Markdown specs
(contract + guidance), pipelines of deterministic components, hierarchical agents bounded by budgets, a typed error model, a CLI, an offline
test suite, generated API reference and guides, and an automated release flow (release-please, versions from git tags, wheels attached to
GitHub Releases). Everything is 0.x: breaking changes are possible and bump the minor version.

## Principles (what we will not trade away)
- **LLMs plan, delegate, repair and interpret; code computes.** No feature may turn model text into data outside declared `runtime: prompt` outputs.
- **The core stays domain-agnostic** and its optional frameworks stay optional.
- **Contracts are declared, validated and tested**: specs in Markdown, errors typed and located, tests offline.

## Non-goals
- A hosted service or a UI product; this is a library and CLI.
- Executing model-written code or formulas.
- Supporting Python older than 3.12.

## Milestones

Dates are intentionally absent: work is picked by priority, and a milestone closes when its issues do.

| Milestone | Theme | Success looks like |
| --- | --- | --- |
| [0.6 Distribution](https://github.com/marcionicolau/spec-agents/milestone/1) | Install by name, with provenance | `pip install` works for every package; release assets are attested; the repository name is settled |
| [0.7 Quality and portability](https://github.com/marcionicolau/spec-agents/milestone/2) | Same behaviour everywhere, checked everywhere | CI on Linux, macOS, Windows and the newest Python; types and coverage per package; docstring style enforced |
| [0.8 Runtime and observability](https://github.com/marcionicolau/spec-agents/milestone/3) | Run faster and see what happened | async/streaming backends and parallel delegations; run traces exportable to standard tooling |
| [0.9 Ecosystem](https://github.com/marcionicolau/spec-agents/milestone/4) | Easy to build and share packs | `scaffold pack`, a from-scratch tutorial, exported skills validated by the official validator |
| [1.0 Stable API](https://github.com/marcionicolau/spec-agents/milestone/5) | A stable, documented contract | API level frozen, deprecation policy in force, public API marked stable or provisional |

The first milestone also carries the PyPI publication ([#76](https://github.com/marcionicolau/spec-agents/issues/76)); the others are
listed on their milestone pages.

## Proposing something
1. Search the [issues](https://github.com/marcionicolau/spec-agents/issues) and the board first.
2. Open an issue with the **feature** or **spec change** form (pick the package; say the problem before the solution).
3. It lands in *Triage*; the maintainer sets package, priority, size and milestone, or says why not. Larger ideas get `stage:needs-design`
   and a short design discussion in the issue before any code.
4. Accepted work becomes *Ready*; anyone may pick it up (comment first). Items marked `good first issue` are the best start.

Priorities are `prio:high` (blocks users or releases), `prio:medium` (planned) and `prio:low` (nice to have). See
[GOVERNANCE.md](GOVERNANCE.md) for how decisions are made.
