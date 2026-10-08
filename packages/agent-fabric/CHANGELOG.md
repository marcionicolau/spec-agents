# Changelog

## [0.9.3](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.9.2...agent-fabric-v0.9.3) (2026-10-08)


### Bug Fixes

* **agent-fabric:** reject ref-shaped strings in params at plan validation ([#145](https://github.com/marcionicolau/spec-agents/issues/145)) ([ff2e0df](https://github.com/marcionicolau/spec-agents/commit/ff2e0dfb0b13fe4f4bd0a0fd02a57d03681cad72))

## [0.9.2](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.9.1...agent-fabric-v0.9.2) (2026-10-07)


### Bug Fixes

* **agent-fabric:** one-shot delegation plan + chained example in ROUTER_RULES ([#142](https://github.com/marcionicolau/spec-agents/issues/142)) ([9c0299f](https://github.com/marcionicolau/spec-agents/commit/9c0299f7d89f85fbea00e1f88d278eab7b5ff4d0))
* **agent-fabric:** show a chained two-delegation plan in ROUTER_RULES ([9c0299f](https://github.com/marcionicolau/spec-agents/commit/9c0299f7d89f85fbea00e1f88d278eab7b5ff4d0))

## [0.9.1](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.9.0...agent-fabric-v0.9.1) (2026-10-07)


### Bug Fixes

* **agent-fabric:** normalize "$steps." prefix in plan references ([#139](https://github.com/marcionicolau/spec-agents/issues/139)) ([c3391d0](https://github.com/marcionicolau/spec-agents/commit/c3391d0c790e3c7785442381e5671c5b64628cf7))

## [0.9.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.8.0...agent-fabric-v0.9.0) (2026-10-05)


### Features

* **agent-fabric:** export run traces (JSON lines / OpenTelemetry) ([#118](https://github.com/marcionicolau/spec-agents/issues/118)) ([9388829](https://github.com/marcionicolau/spec-agents/commit/93888294af1615e57ed20806d4037c2db8c5b60b))

## [0.8.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.7.0...agent-fabric-v0.8.0) (2026-10-02)


### Features

* **agent-fabric:** async and streaming LLM backends ([#111](https://github.com/marcionicolau/spec-agents/issues/111)) ([ed67381](https://github.com/marcionicolau/spec-agents/commit/ed67381eb085b401c462a28ea956858fc0564688))
* **agent-fabric:** run independent router delegations in parallel ([#112](https://github.com/marcionicolau/spec-agents/issues/112)) ([cf82389](https://github.com/marcionicolau/spec-agents/commit/cf8238979560c98ebd4c716c9c2060761282f7cd))
* **agent-fabric:** stream LLM answer text to the live view ([#113](https://github.com/marcionicolau/spec-agents/issues/113)) ([a6fba84](https://github.com/marcionicolau/spec-agents/commit/a6fba84c4f093119cbf77edf01c9ef68dec3e9e9))

## [0.7.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.6.0...agent-fabric-v0.7.0) (2026-10-02)


### Features

* **agent-fabric:** scaffold whole domain packs with `scaffold pack` ([9e0746f](https://github.com/marcionicolau/spec-agents/commit/9e0746fbaeb325b483258ab95f1dc454ec93c26d))
* **agent-fabric:** scaffold whole domain packs with scaffold pack ([#108](https://github.com/marcionicolau/spec-agents/issues/108)) ([9e0746f](https://github.com/marcionicolau/spec-agents/commit/9e0746fbaeb325b483258ab95f1dc454ec93c26d))

## [0.6.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.5.1...agent-fabric-v0.6.0) (2026-10-02)


### Features

* **agent-fabric:** the CLI discovers installed domain packs by default ([#106](https://github.com/marcionicolau/spec-agents/issues/106)) ([cb8a75e](https://github.com/marcionicolau/spec-agents/commit/cb8a75ede568bc8460363685bd50d40e6041b4b2)), closes [#104](https://github.com/marcionicolau/spec-agents/issues/104)

## [0.5.1](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.5.0...agent-fabric-v0.5.1) (2026-10-02)


### Bug Fixes

* document the spec-agents-* distribution names in the package READMEs ([#96](https://github.com/marcionicolau/spec-agents/issues/96)) ([fffad88](https://github.com/marcionicolau/spec-agents/commit/fffad88e5c8405bb01c7d9dddf66b7cf52a13e28)), closes [#76](https://github.com/marcionicolau/spec-agents/issues/76)

## [0.5.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.4.0...agent-fabric-v0.5.0) (2026-10-02)


### Features

* **agent-fabric:** core/pack API level contract ([#75](https://github.com/marcionicolau/spec-agents/issues/75)) ([d880a74](https://github.com/marcionicolau/spec-agents/commit/d880a744481b888e1e435a1c0d482e44fa942e03)), closes [#20](https://github.com/marcionicolau/spec-agents/issues/20)
* **agent-fabric:** define the public API surface with __all__, fix __version__ ([#57](https://github.com/marcionicolau/spec-agents/issues/57)) ([c9ab564](https://github.com/marcionicolau/spec-agents/commit/c9ab56432fb2e95c5f1a1ebd9428a23c42b9d89f)), closes [#56](https://github.com/marcionicolau/spec-agents/issues/56)

## [0.4.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.3.0...agent-fabric-v0.4.0) (2026-10-01)


### Features

* **agent-fabric:** export skills as spec-compliant Agent Skills ([#54](https://github.com/marcionicolau/spec-agents/issues/54)) ([bb2b9bb](https://github.com/marcionicolau/spec-agents/commit/bb2b9bbf395bb90107a8bdcb47aad5516d0aadab)), closes [#22](https://github.com/marcionicolau/spec-agents/issues/22)

## [0.3.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.2.0...agent-fabric-v0.3.0) (2026-10-01)


### Features

* **agent-fabric:** gate deterministic eval suites on stored baselines ([#52](https://github.com/marcionicolau/spec-agents/issues/52)) ([378b2fd](https://github.com/marcionicolau/spec-agents/commit/378b2fdbed74a0213dc142720ae05c0a17525b6f)), closes [#24](https://github.com/marcionicolau/spec-agents/issues/24)

## [0.2.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.1.0...agent-fabric-v0.2.0) (2026-10-01)


### Features

* **agent-fabric:** fail PRs whose SKILL.md contract changes lack a version bump ([#51](https://github.com/marcionicolau/spec-agents/issues/51)) ([ac97619](https://github.com/marcionicolau/spec-agents/commit/ac97619390756378cb1b8cdd9145814a93417ba0))
* **agent-fabric:** lint skill descriptions for what-and-when style ([#49](https://github.com/marcionicolau/spec-agents/issues/49)) ([321a834](https://github.com/marcionicolau/spec-agents/commit/321a8343fa8f8953a7bea7974841858015e9c890)), closes [#23](https://github.com/marcionicolau/spec-agents/issues/23)

## [0.1.0](https://github.com/marcionicolau/spec-agents/compare/agent-fabric-v0.0.1...agent-fabric-v0.1.0) (2026-10-01)


### Features

* **agent-fabric:** enforce architecture boundaries and type-check the core; fix live view crash ([#38](https://github.com/marcionicolau/spec-agents/issues/38)) ([45b277f](https://github.com/marcionicolau/spec-agents/commit/45b277f586b14bf966d13f3eaacb66df52f5649b))


### Bug Fixes

* **statistics:** warn on perfect collinearity with inf VIF; ci: require lowest-versions job ([#35](https://github.com/marcionicolau/spec-agents/issues/35)) ([e1502a1](https://github.com/marcionicolau/spec-agents/commit/e1502a1a7d0cfb65dd65e6087843ae6bddc4a378))
