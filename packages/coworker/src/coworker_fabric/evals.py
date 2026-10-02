"""Offline evaluation of ``context_select``: does it pick the files a developer would need for a task?

Cases label, for a task (and optionally focus files), the files that must be in the context. The score rewards
recall (did we get them?) and early ranking, and mildly penalises noise.  Deterministic, no LLM.

    python -m coworker_fabric.evals --root . [--cases examples/evals/context_cases.yaml] [--budget 6000] [--max-files 8]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_fabric import build_registry
from agent_fabric.component import ArtifactStore, StepContext


class ContextCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    task: str
    expected: list[str] = Field(min_length=1, description="files that must be selected (relative to the root)")
    focus_files: list[str] = Field(default_factory=list)
    min_recall: float = Field(1.0, ge=0, le=1)


class CaseScore(BaseModel):
    name: str
    recall: float
    precision: float
    first_hit_rank: int | None
    n_selected: int
    tokens: int
    missing: list[str]
    score: float


def load_cases(path: str | Path) -> list[ContextCase]:
    """Load labelled context-selection cases from a YAML file (a list, or a mapping with a ``cases`` key)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return [ContextCase.model_validate(c) for c in (raw.get("cases", []) if isinstance(raw, dict) else raw)]


def score_selection(case: ContextCase, selected: list[str], tokens: int) -> CaseScore:
    """Score one context selection against its case.

    ``0.7 * recall + 0.2 * (1 / rank of the first expected file) + 0.1 * precision``; also reports the missing files and the tokens used.
    """
    exp, got = set(case.expected), set(selected)
    hits = exp & got
    recall = len(hits) / len(exp)
    precision = len(hits) / len(got) if got else 0.0
    ranks = [i + 1 for i, p in enumerate(selected) if p in exp]
    # 0.7 recall + 0.2 ranking (first hit at rank 1 = full credit) + 0.1 precision
    score = 0.7 * recall + 0.2 * (1 / ranks[0] if ranks else 0.0) + 0.1 * precision
    return CaseScore(
        name=case.name,
        recall=round(recall, 3),
        precision=round(precision, 3),
        first_hit_rank=ranks[0] if ranks else None,
        n_selected=len(selected),
        tokens=tokens,
        missing=sorted(exp - got),
        score=round(score, 4),
    )


# Files the labelled cases of this repository can refer to. Indexing everything (docs/, tools/, examples/) lets new files that merely share
# vocabulary with a task outrank the right ones, so the score would drift with unrelated additions.
REPO_EVAL_INCLUDE = ["packages/**/*.py", "tests/**/*.py"]


def run_cases(
    root: str | Path, cases: list[ContextCase], *, include: list[str] | None = None, **select_params: Any
) -> list[CaseScore]:
    """Index ``root`` once, then run ``context_select`` for every case with ``select_params`` (budget, hops, ...).

    ``include`` limits the indexed files (globs relative to ``root``); the default is the indexer's own default (every ``.py`` file).
    """
    from .domain import register

    os.environ.setdefault("COWORKER_ALLOWED_ROOTS", str(Path(root).resolve()))
    registry = build_registry([register])

    def execute(name: str, inputs: dict, params: dict) -> dict:
        comp = registry.get(name)
        store = ArtifactStore()
        comp.execute(inputs, params, StepContext(store, "e", comp.spec, registry.types))
        return store

    index = execute("repo_index", {}, {"root": str(root), **({"include": include} if include else {})}).get("e.index")
    out = []
    for case in cases:
        params = {"task": case.task, "focus_files": case.focus_files, **select_params}
        ctx = execute("context_select", {"index": index}, params).get("e.context")
        sel = ctx["selected"]
        out.append(score_selection(case, [s["path"] for s in sel], sum(s["tokens"] for s in sel)))
    return out


def table(scores: list[CaseScore]) -> str:
    rows = [f"{'case':30} {'score':>5} {'recall':>6} {'prec':>5} {'rank':>4} {'files':>5} {'tokens':>6}  missing"]
    rows += [
        f"{s.name:30} {s.score:5.2f} {s.recall:6.2f} {s.precision:5.2f} {s.first_hit_rank or '-'!s:>4} {s.n_selected:5d} {s.tokens:6d}  "
        f"{', '.join(s.missing)}"
        for s in scores
    ]
    n = len(scores)
    rows.append(
        f"mean score {sum(s.score for s in scores) / n:.3f}   recall {sum(s.recall for s in scores) / n:.3f}   "
        f"precision {sum(s.precision for s in scores) / n:.3f}   tokens {sum(s.tokens for s in scores) // n}"
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m coworker_fabric.evals", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--cases", default="examples/evals/context_cases.yaml")
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--max-files", type=int, default=8)
    ap.add_argument("--hops", type=int, default=1)
    ap.add_argument("--cutoff", type=float, default=0.5, help="relative_cutoff passed to context_select")
    ap.add_argument(
        "--include",
        nargs="+",
        default=REPO_EVAL_INCLUDE,
        help="globs (relative to --root) of the files to index; default: this repository's packages and tests",
    )
    ap.add_argument(
        "--sweep", nargs="+", type=float, help="print the summary line for each relative_cutoff value and exit"
    )
    a = ap.parse_args(argv)
    if a.sweep:
        cases = load_cases(a.cases)
        for c in a.sweep:
            print(
                f"cutoff {c:4.2f}  "
                + table(
                    run_cases(
                        a.root,
                        cases,
                        include=a.include,
                        token_budget=a.budget,
                        max_files=a.max_files,
                        hops=a.hops,
                        relative_cutoff=c,
                    )
                ).splitlines()[-1]
            )
        return
    scores = run_cases(
        a.root,
        load_cases(a.cases),
        include=a.include,
        token_budget=a.budget,
        max_files=a.max_files,
        hops=a.hops,
        relative_cutoff=a.cutoff,
    )
    print(table(scores))
    sys.exit(0 if all(s.recall >= c.min_recall for s, c in zip(scores, load_cases(a.cases))) else 1)


if __name__ == "__main__":
    main()


__all__ = [
    "REPO_EVAL_INCLUDE",
    "CaseScore",
    "ContextCase",
    "load_cases",
    "run_cases",
    "score_selection",
]
