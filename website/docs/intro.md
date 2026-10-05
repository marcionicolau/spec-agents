---
id: intro
slug: /
title: spec-agents
sidebar_label: Introduction
---

**spec-agents** (the `agent-fabric` toolkit) lets you build pipelines and agent teams from Markdown specs, with one rule above all:
**LLMs plan, delegate, repair and interpret; code computes.** A model never produces a result by itself. Every number, table and file
comes from a deterministic component that a spec declares and the toolkit validates before it runs.

## What you get

- **Specs in Markdown.** A component, pipeline or agent is a `SKILL.md` / `AGENT.md` file: the YAML frontmatter is the contract
  (ports, params, budgets), the body is guidance for the model.
- **Verified before it runs.** Plans are validated against the registry and report *all* problems at once as typed, located errors.
- **Bounded agents.** Depth, delegations and LLM calls are budgeted per run, so a team cannot loop forever.
- **Offline-first.** Everything in this guide runs without a model; a scripted backend plays the LLM.
- **Domain packs.** The core knows no domain; packs add components and pipelines for statistics, lakehouse engineering, code
  review and text.

## Where to start

| I want to… | Go to |
| --- | --- |
| install it and run something in five minutes | [Installation](installation.md) then [Quickstart](quickstart.mdx) |
| use a domain pack on my own data | [Domain packs](packs/index.md) |
| understand a failure | [Handle errors](how-to/handle-errors.mdx) |
| point it at a real model | [Use a real model](how-to/real-model.mdx) |
| look up an API, or contribute | [API reference and contributor guides](pathname:///spec-agents/reference/) |

The code on these pages is not pasted: each block is a script from
[`examples/docs/`](https://github.com/marcionicolau/spec-agents/tree/main/examples/docs) that the test suite runs offline, so what you see works.
