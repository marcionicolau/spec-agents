## Summary
<!-- What and why. Link the issue: Closes #N -->

## Checklist
- [ ] PR title is conventional with a package scope (`feat(statistics): ...`); scopes: agent-fabric, statistics, lakehouse, coworker, ci, deps, docs
- [ ] Tests added/updated and `uv run pytest -q` passes
- [ ] `uv run ruff check .` clean
- [ ] Spec lint `--strict` passes (if SKILL.md/AGENT.md changed)
- [ ] SKILL.md `version:` bumped for contract changes (minor = optional field, major = breaking)
- [ ] `run_evals.py --mode live` run for guidance/prompt/model-alias changes (attach `mean_score`)
