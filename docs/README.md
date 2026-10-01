# Documentation

| Document                                  | Contents                                                                                           |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [architecture.md](architecture.md)        | Stack, run flow, patterns, full directory map                                                      |
| [extending.md](extending.md)              | Adding a component (code or `runtime: prompt`), a pipeline, an artifact type                       |
| [agents.md](agents.md)                    | Agent trees: `fabric.md`, `AGENT.md`, kinds/backends, router plan, budget, fallbacks               |
| [error-model.md](error-model.md)          | `FabricError` categories and the `loc`/`type`/`msg`/`hint` rules                                   |
| [maintenance.md](maintenance.md)          | What to run when you change a contract, prose or a model alias; lint and eval rules; pack rules   |
| [releasing.md](releasing.md)              | Versions from git tags, release-please flow, labels and issue stages, CI gate                      |

Rules for contributors and coding agents: [../CLAUDE.md](../CLAUDE.md). Contribution workflow: [../CONTRIBUTING.md](../CONTRIBUTING.md).
Package READMEs: [agent-fabric](../packages/agent-fabric/README.md), [statistics](../packages/statistics/README.md),
[lakehouse](../packages/lakehouse/README.md), [coworker](../packages/coworker/README.md), [text-pack](../packages/text-pack/README.md).
