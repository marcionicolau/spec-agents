# Documentation

This folder is the source of the **contributor guides and API reference** (mkdocs-material + mkdocstrings). The user-facing guide
(installation, quickstart, a guide per domain pack, how-tos) is a Docusaurus site in [`website/`](https://github.com/marcionicolau/spec-agents/tree/main/website);
its code blocks are the scripts in `examples/docs/`, which `tests/test_docs_examples.py` runs offline, so the examples cannot drift.

Both are published as **one GitHub Pages site**: Docusaurus at the root, MkDocs under `/reference/`
(`.github/workflows/docs.yml`): https://marcionicolau.github.io/spec-agents/.

| Command | Does |
| --- | --- |
| `just docs-all` (alias `just docs`) | builds both into `build/site` (strict: warnings and broken links fail); needs Node 24 (`.node-version`) |
| `just docs-doc` / `just docs-api` | only the Docusaurus guide / only MkDocs (`build/site/reference`) |
| `just docs-serve` / `just docs-serve doc` | live preview of MkDocs (port 8000) / Docusaurus (port 3000) |

The **API reference** pages are generated from the code at build time (`docs/gen_reference.py`): one page per package, listing only the
names in each module's `__all__`, rendered from the docstrings (Google style). CI builds both on every PR and keeps the result as the
`docs-site` artifact.

**Where does new content go?** How to *use* something, with a runnable example: `website/docs/` (add the script under `examples/docs/`
and embed it with the `Example` component). How the project *works* or how to *change* it: here in `docs/`.

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
