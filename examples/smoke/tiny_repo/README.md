# tiny_repo

Minimal repository used by the coworker smoke test (issue: live smoke of
`context_select` → `patch_propose`). `calc.py` intentionally contains a bug:
`mean([])` raises `ZeroDivisionError` instead of a clear error.
