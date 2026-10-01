# Documentation

This folder is also the source of the documentation site (mkdocs-material + mkdocstrings): `just docs` builds it into `build/site`
(warnings fail the build), `just docs-serve` previews it. The **API reference** pages are generated from the code at build time
(`docs/gen_reference.py`): one page per package, listing only the names in each module's `__all__`, rendered from the docstrings
(Google style). CI builds the site on every PR and keeps it as the `docs-site` artifact; it is not published (no GitHub Pages on a
private repo on the free plan).

| Document                                  | Contents                                                                                           |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [quickstart.md](quickstart.md)            | Install, run a pipeline, run an agent tree (all offline), use a real model, check specs             |
| [concepts.md](concepts.md)                | The mental model on one page                                                                       |
| [packs.md](packs.md)                      | The domain packs and what each provides                                                            |
| [architecture.md](architecture.md)        | Stack, run flow, patterns, full directory map                                                      |
| [extending.md](extending.md)              | Adding a component (code or `runtime: prompt`), a pipeline, an artifact type                       |
| [agents.md](agents.md)                    | Agent trees: `fabric.md`, `AGENT.md`, kinds/backends, router plan, budget, fallbacks               |
| [error-model.md](error-model.md)          | `FabricError` categories and the `loc`/`type`/`msg`/`hint` rules                                   |
| [maintenance.md](maintenance.md)          | What to run when you change a contract, prose or a model alias; lint and eval rules; pack rules   |
| [releasing.md](releasing.md)              | Versions from git tags, release-please flow, labels and issue stages, CI gate                      |

Rules for contributors and coding agents: [../CLAUDE.md](https://github.com/marcionicolau/spec-agents/blob/main/CLAUDE.md). Contribution workflow: [../CONTRIBUTING.md](https://github.com/marcionicolau/spec-agents/blob/main/CONTRIBUTING.md).
Package READMEs: [agent-fabric](https://github.com/marcionicolau/spec-agents/blob/main/packages/agent-fabric/README.md), [statistics](https://github.com/marcionicolau/spec-agents/blob/main/packages/statistics/README.md),
[lakehouse](https://github.com/marcionicolau/spec-agents/blob/main/packages/lakehouse/README.md), [coworker](https://github.com/marcionicolau/spec-agents/blob/main/packages/coworker/README.md), [text-pack](https://github.com/marcionicolau/spec-agents/blob/main/packages/text-pack/README.md).
