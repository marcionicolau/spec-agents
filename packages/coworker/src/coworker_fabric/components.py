"""Coworker components: index a repository, choose the context for a task, pack it, review it, validate patches."""

from __future__ import annotations

import ast
import difflib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_fabric.component import Component, ComponentParams, ComponentResult, StepContext
from agent_fabric.errors import ErrorDetail, suggest
from agent_fabric.registry import component

from .analysis import (
    ROOTS_ENV,
    SKIP_DIRS,
    Scorer,
    allowed_roots,
    analyse_python,
    module_name,
    pick_symbols,
    resolve_import,
    review_source,
    root_allowed,
    safe_path,
    token_estimate,
    words,
)

RULES = (
    "syntax_error",
    "long_function",
    "high_complexity",
    "many_params",
    "mutable_default",
    "missing_return_annotation",
    "bare_except",
    "swallowed_exception",
    "eval_exec",
    "print_call",
    "unused_import",
    "todo_comment",
)
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _root_check(root: str) -> list[ErrorDetail]:
    if not Path(root).is_dir():
        return [
            ErrorDetail(
                loc=("params", "root"),
                type="root_not_found",
                msg=f"{root} is not a directory",
                hint="use the repository path as seen by the machine running this step",
            )
        ]
    if not root_allowed(root):
        return [
            ErrorDetail(
                loc=("params", "root"),
                type="root_not_allowed",
                input=root,
                msg="this directory is outside the allowed roots",
                hint=f"allowed: {[str(r) for r in allowed_roots()]}; set {ROOTS_ENV} (os.pathsep-separated) to allow more",
            )
        ]
    return []


# ============================================================================ repo_index
class RepoIndexParams(ComponentParams):
    root: str
    include: list[str] = Field(default_factory=lambda: ["**/*.py"], min_length=1, max_length=8)
    exclude_dirs: list[str] = Field(default_factory=list, max_length=20)
    max_files: int = Field(2000, ge=1, le=20000)
    max_file_kb: int = Field(512, ge=1, le=4096)


class LargeFile(BaseModel):
    path: str
    tokens: int


class RepoIndexResult(ComponentResult):
    n_files: int
    n_python: int
    n_symbols: int
    n_edges: int
    total_lines: int
    total_tokens: int
    largest: list[LargeFile]
    parse_errors: list[str]


@component("repo_index")
class RepoIndex(Component[RepoIndexParams, RepoIndexResult]):
    Params = RepoIndexParams
    Result = RepoIndexResult

    def extra_checks(self, inputs: dict, params: RepoIndexParams) -> list[ErrorDetail]:
        errs = _root_check(params.root)
        for i, pat in enumerate(params.include):
            if pat.startswith("/") or ".." in Path(pat).parts:
                errs.append(
                    ErrorDetail(
                        loc=("params", "include", i),
                        type="bad_glob",
                        input=pat,
                        msg="globs must be relative and stay inside the root",
                        hint="e.g. 'src/**/*.py'",
                    )
                )
        return errs

    def compute(self, inputs: dict, params: RepoIndexParams, ctx: StepContext) -> RepoIndexResult:
        root = Path(params.root).resolve()
        skip = SKIP_DIRS | set(params.exclude_dirs)
        found: dict[str, Path] = {}
        for pat in params.include:
            for p in root.glob(pat):
                rel = p.relative_to(root)
                if p.is_file() and not (set(rel.parts[:-1]) & skip) and p.resolve().is_relative_to(root):
                    found[rel.as_posix()] = p
        warns: list[str] = []
        paths = sorted(found)
        if len(paths) > params.max_files:
            warns.append(f"{len(paths)} files match; only the first {params.max_files} were indexed")
            paths = paths[: params.max_files]
        files: list[dict[str, Any]] = []
        raw_imports: dict[str, list] = {}
        skipped = 0
        for rel in paths:
            p = found[rel]
            if p.stat().st_size > params.max_file_kb * 1024:
                skipped += 1
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            entry: dict[str, Any] = {
                "path": rel,
                "module": module_name(rel) if rel.endswith(".py") else "",
                "lines": text.count("\n") + 1,
                "tokens": token_estimate(text),
                "symbols": [],
                "imports": [],
                "terms": {},
            }
            if rel.endswith(".py"):
                info = analyse_python(text)
                entry["symbols"] = info["symbols"]
                entry["terms"] = info["terms"]
                if "error" in info:
                    entry["error"] = info["error"]
                raw_imports[rel] = info["imports"]
            files.append(entry)
        if skipped:
            warns.append(f"{skipped} file(s) larger than {params.max_file_kb} KB were skipped")
        by_module = {f["module"]: f["path"] for f in files if f["module"]}
        modules = set(by_module)
        edges: set[tuple[str, str]] = set()
        for f in files:
            for mod, level, name in raw_imports.get(f["path"], []):
                target = resolve_import(mod, level, name, f["module"], f["path"].endswith("__init__.py"), modules)
                if target and by_module[target] != f["path"]:
                    edges.add((f["path"], by_module[target]))
        for f in files:
            f["imports"] = sorted(t for s, t in edges if s == f["path"])
            f.pop("module")
        index = {"root": str(root), "files": files, "edges": sorted(map(list, edges))}
        ctx.emit("index", index)
        errors = [f"{f['path']}: {f['error']}" for f in files if f.get("error")]
        largest = sorted(files, key=lambda f: -f["tokens"])[:5]
        return RepoIndexResult(
            n_files=len(files),
            n_python=sum(f["path"].endswith(".py") for f in files),
            n_symbols=sum(len(f["symbols"]) for f in files),
            n_edges=len(edges),
            total_lines=sum(f["lines"] for f in files),
            total_tokens=sum(f["tokens"] for f in files),
            largest=[LargeFile(path=f["path"], tokens=f["tokens"]) for f in largest],
            parse_errors=errors[:10],
            warnings=warns,
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return (
            f"Indexed {r['n_files']} files ({r['n_symbols']} symbols, {r['n_edges']} import links, ~{r['total_tokens']} tokens).",
            [f"largest: {x['path']} (~{x['tokens']} tokens)" for x in r["largest"][:3]],
        )


# ============================================================================ context_select
class ContextSelectParams(ComponentParams):
    task: str = Field(min_length=3, max_length=500)
    focus_files: list[str] = Field(default_factory=list, max_length=20)
    token_budget: int = Field(8000, ge=200, le=200000)
    max_files: int = Field(12, ge=1, le=60)
    hops: int = Field(1, ge=0, le=3)
    include_tests: bool = True
    partial_files: bool = Field(
        True, description="large files that only partly match contribute just their matching symbols"
    )
    relative_cutoff: float = Field(
        0.5, ge=0, le=1, description="drop non-focus files scoring below this fraction of the best one"
    )


class SelectedFile(BaseModel):
    path: str
    tokens: int
    score: float
    reasons: list[str]
    ranges: list[list[int]] | None = Field(
        None, description="line ranges [start, end] when only part of the file is selected"
    )
    symbols: list[str] = Field(default_factory=list)


class ContextSelectResult(ComponentResult):
    task: str
    selected: list[SelectedFile]
    tokens_used: int
    token_budget: int
    n_candidates: int
    omitted: list[str]


@component("context_select")
class ContextSelect(Component[ContextSelectParams, ContextSelectResult]):
    Params = ContextSelectParams
    Result = ContextSelectResult

    def extra_checks(self, inputs: dict, params: ContextSelectParams) -> list[ErrorDetail]:
        by_path = {f["path"]: f for f in inputs["index"]["files"]}
        errs = [
            ErrorDetail(
                loc=("params", "focus_files", i),
                type="file_not_in_index",
                input=p,
                msg=f"'{p}' is not in the index",
                hint=suggest(p, by_path) or "paths are relative to the indexed root",
            )
            for i, p in enumerate(params.focus_files)
            if p not in by_path
        ]
        if errs:
            return errs
        focus_tokens = sum(by_path[p]["tokens"] for p in params.focus_files)
        if focus_tokens > params.token_budget:
            errs.append(
                ErrorDetail(
                    loc=("params", "token_budget"),
                    type="focus_exceeds_budget",
                    msg=f"the focus files alone need ~{focus_tokens} tokens, budget is {params.token_budget}",
                    hint="raise token_budget or focus on fewer files",
                )
            )
        if not params.focus_files and not words(params.task):
            errs.append(
                ErrorDetail(
                    loc=("params", "task"),
                    type="task_too_vague",
                    msg="no focus files and no concrete words to search for",
                    hint="name a module, class or feature, or set focus_files",
                )
            )
        return errs

    def compute(self, inputs: dict, params: ContextSelectParams, ctx: StepContext) -> ContextSelectResult:
        index = inputs["index"]
        files = {f["path"]: f for f in index["files"]}
        neighbours: dict[str, set[str]] = defaultdict(set)
        for a, b in index["edges"]:
            neighbours[a].add(b)
            neighbours[b].add(a)
        scorer = Scorer(index["files"], params.task)
        wants_tests = any(w in ("test", "tests", "testing", "pytest") for w in words(params.task))

        dist: dict[str, int] = {p: 0 for p in params.focus_files}
        queue = deque(params.focus_files)
        while queue:
            cur = queue.popleft()
            if dist[cur] >= params.hops:
                continue
            for nb in neighbours[cur]:
                if nb not in dist:
                    dist[nb] = dist[cur] + 1
                    queue.append(nb)

        scored: dict[str, tuple[float, list[str]]] = {}
        stems_ = {Path(p).stem for p in params.focus_files}
        for path, f in files.items():
            score, reasons = 0.0, []
            if path in params.focus_files:
                score, reasons = 1.0, ["focus file"]
            elif path in dist:
                score = 0.6 / dist[path]
                links = sorted(set(params.focus_files) & neighbours[path]) if dist[path] == 1 else []
                reasons.append(
                    f"imports or is imported by {', '.join(links)}"
                    if links
                    else f"{dist[path]} import hops from the focus"
                )
            name = Path(path).name
            paired = params.include_tests and any(name in (f"test_{s}.py", f"{s}_test.py") for s in stems_)
            if paired:
                score, reasons = max(score, 0.8), reasons + ["test of a focus file"]
            term_score, hits = scorer.file(f)
            if term_score and (name.startswith("test_") or "tests" in Path(path).parts) and not (wants_tests or paired):
                term_score *= 0.5  # tests echo the vocabulary of the code they test; do not let them crowd it out
            if term_score:
                score += 0.5 * term_score
                reasons.append("matches task terms: " + ", ".join(hits))
            if score > 0:
                scored[path] = (round(score, 3), reasons)

        rest = [scored[p][0] for p in scored if p not in params.focus_files]
        floor = params.relative_cutoff * max(rest, default=0.0)
        scored = {p: v for p, v in scored.items() if p in params.focus_files or v[0] >= floor}
        order = sorted(scored, key=lambda p: (p not in params.focus_files, -scored[p][0], files[p]["tokens"], p))
        selected: list[SelectedFile] = []
        used, omitted = 0, []
        big = max(300, params.token_budget // 4)  # a file taking over a quarter of the budget is only read in part
        for p in order:
            f, tokens = files[p], files[p]["tokens"]
            entry = SelectedFile(path=p, tokens=tokens, score=scored[p][0], reasons=scored[p][1])
            if p not in params.focus_files:
                if len(selected) >= params.max_files:
                    omitted.append(p)
                    continue
                if params.partial_files and tokens > big and f["symbols"]:
                    room = min(params.token_budget - used, int(tokens * 0.6), max(big, 2500))
                    part = pick_symbols(f, scorer, room) if room > 300 else None
                    if part is not None:
                        ranges, names, cost = part
                        entry = entry.model_copy(
                            update={
                                "tokens": cost,
                                "ranges": ranges,
                                "symbols": names,
                                "reasons": scored[p][1]
                                + [f"only the matching symbols ({len(names)} of {len(f['symbols'])})"],
                            }
                        )
                        tokens = cost
                if used + tokens > params.token_budget:
                    omitted.append(p)
                    continue
            selected.append(entry)
            used += entry.tokens
        warns = []
        strong = [p for p in omitted if scored[p][0] >= 0.6]
        if strong:
            warns.append(
                f"{len(strong)} relevant file(s) did not fit: {', '.join(strong[:3])}; raise token_budget or max_files"
            )
        if not selected:
            warns.append("nothing in the index matched the task")
        ctx.emit(
            "context", {"root": index["root"], "task": params.task, "selected": [s.model_dump() for s in selected]}
        )
        return ContextSelectResult(
            task=params.task,
            selected=selected,
            tokens_used=used,
            token_budget=params.token_budget,
            n_candidates=len(scored),
            omitted=omitted[:10],
            warnings=warns,
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return (
            f"Selected {len(r['selected'])} files (~{r['tokens_used']} of {r['token_budget']} tokens).",
            [f"{s['path']}: {'; '.join(s['reasons'])}" for s in r["selected"][:6]],
        )


# ============================================================================ context_pack
class ContextPackParams(ComponentParams):
    max_chars_per_file: int = Field(20000, ge=500, le=200000)


class ContextPackResult(ComponentResult):
    n_files: int
    n_chars: int
    truncated: list[str]


@component("context_pack")
class ContextPack(Component[ContextPackParams, ContextPackResult]):
    Params = ContextPackParams
    Result = ContextPackResult

    def extra_checks(self, inputs: dict, params: ContextPackParams) -> list[ErrorDetail]:
        root = Path(inputs["context"]["root"])
        errs = _root_check(str(root))
        for i, s in enumerate(inputs["context"]["selected"]):
            p = safe_path(root, s["path"])
            if p is None or not p.is_file():
                errs.append(
                    ErrorDetail(
                        loc=("inputs", "context", "selected", i),
                        type="file_missing",
                        input=s["path"],
                        msg=f"{s['path']} no longer exists under the root",
                        hint="re-run repo_index",
                    )
                )
        return errs

    def compute(self, inputs: dict, params: ContextPackParams, ctx: StepContext) -> ContextPackResult:
        root = Path(inputs["context"]["root"])
        parts, truncated = [f"# Context for: {inputs['context']['task']}", ""], []
        for s in inputs["context"]["selected"]:
            text = (safe_path(root, s["path"]) or root).read_text(encoding="utf-8", errors="replace")
            if s.get("ranges"):
                lines = text.splitlines()
                blocks = [f"# --- lines {a}-{b} ---\n" + "\n".join(lines[a - 1 : b]) for a, b in s["ranges"]]
                text = "\n# ...\n".join(blocks)
            if len(text) > params.max_chars_per_file:
                text = text[: params.max_chars_per_file] + "\n# ... truncated ..."
                truncated.append(s["path"])
            lang = "python" if s["path"].endswith(".py") else ""
            partial = f", partial: {', '.join(s['symbols'][:6])}" if s.get("ranges") else ""
            parts += [f"## {s['path']}  ({'; '.join(s['reasons'])}{partial})", f"```{lang}", text.rstrip(), "```", ""]
        bundle = "\n".join(parts)
        ctx.emit("bundle", bundle)
        return ContextPackResult(
            n_files=len(inputs["context"]["selected"]),
            n_chars=len(bundle),
            truncated=truncated,
            warnings=[f"{len(truncated)} file(s) truncated"] if truncated else [],
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return f"Packed {r['n_files']} files into {r['n_chars']} characters.", [
            f"truncated: {t}" for t in r["truncated"]
        ]


# ============================================================================ code_review
class CodeReviewParams(ComponentParams):
    max_function_lines: int = Field(60, ge=10, le=500)
    max_complexity: int = Field(10, ge=3, le=50)
    max_params: int = Field(6, ge=2, le=20)
    disable: list[str] = Field(default_factory=list)
    max_findings: int = Field(100, ge=1, le=500)

    @field_validator("disable")
    @classmethod
    def _known_rules(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in RULES]
        if bad:
            raise ValueError(f"unknown rules {bad}; available: {list(RULES)}")
        return v


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    line: int
    rule: str
    severity: str
    message: str
    suggestion: str


class CodeReviewResult(ComponentResult):
    n_files: int
    n_findings: int
    by_severity: dict[str, int]
    by_rule: dict[str, int]
    findings: list[Finding]


@component("code_review")
class CodeReview(Component[CodeReviewParams, CodeReviewResult]):
    Params = CodeReviewParams
    Result = CodeReviewResult

    def extra_checks(self, inputs: dict, params: CodeReviewParams) -> list[ErrorDetail]:
        root = Path(inputs["context"]["root"])
        errs = _root_check(str(root))
        if not any(s["path"].endswith(".py") for s in inputs["context"]["selected"]):
            errs.append(
                ErrorDetail(
                    loc=("inputs", "context"),
                    type="no_python_files",
                    msg="the context has no Python files to review",
                    hint="select Python files or widen the focus",
                )
            )
        return errs

    def compute(self, inputs: dict, params: CodeReviewParams, ctx: StepContext) -> CodeReviewResult:
        root = Path(inputs["context"]["root"])
        found: list[dict[str, Any]] = []
        n = 0
        for s in inputs["context"]["selected"]:
            p = safe_path(root, s["path"])
            if not s["path"].endswith(".py") or p is None or not p.is_file():
                continue
            n += 1
            hits = review_source(
                s["path"],
                p.read_text(encoding="utf-8", errors="replace"),
                max_function_lines=params.max_function_lines,
                max_complexity=params.max_complexity,
                max_params=params.max_params,
            )
            if s.get("ranges"):  # only part of the file is in the context: report what falls inside it
                hits = [h for h in hits if any(a <= h["line"] <= b for a, b in s["ranges"])]
            found += hits
        found = [f for f in found if f["rule"] not in params.disable]
        found.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["path"], f["line"]))
        by_sev, by_rule = defaultdict(int), defaultdict(int)
        for f in found:
            by_sev[f["severity"]] += 1
            by_rule[f["rule"]] += 1
        kept = found[: params.max_findings]
        ctx.emit("findings", kept)
        warns = (
            [f"{len(found) - len(kept)} lower-priority findings were cut (max_findings)"]
            if len(found) > len(kept)
            else []
        )
        return CodeReviewResult(
            n_files=n,
            n_findings=len(found),
            by_severity=dict(by_sev),
            by_rule=dict(by_rule),
            findings=[Finding(**f) for f in kept],
            warnings=warns,
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        sev = ", ".join(f"{v} {k}" for k, v in sorted(r["by_severity"].items(), key=lambda kv: SEVERITY_ORDER[kv[0]]))
        return (
            f"{r['n_findings']} findings in {r['n_files']} files" + (f" ({sev})." if sev else "."),
            [f"{f['path']}:{f['line']} {f['rule']}: {f['message']}" for f in r["findings"][:6]],
        )


# ============================================================================ patch_propose
class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    old: str = Field(min_length=1, description="exact text to replace; must occur exactly once in the file")
    new: str


class PatchProposeParams(ComponentParams):
    root: str
    edits: list[Edit] = Field(min_length=1, max_length=10)
    max_changed_lines: int = Field(200, ge=1, le=2000)


class FilePatch(BaseModel):
    path: str
    additions: int
    deletions: int


class PatchProposeResult(ComponentResult):
    files: list[FilePatch]
    additions: int
    deletions: int


def _apply(params: PatchProposeParams, context: dict | None) -> tuple[dict[str, tuple[str, str]], list[ErrorDetail]]:
    """Apply the edits in memory. Returns {path: (before, after)} and located errors. Never writes."""
    root, errs = Path(params.root), []
    allowed = {s["path"] for s in context["selected"]} if context else None
    texts: dict[str, tuple[str, str]] = {}
    for i, e in enumerate(params.edits):
        loc = ("params", "edits", i)
        p = safe_path(root, e.path)
        if p is None:
            errs.append(
                ErrorDetail(
                    loc=loc + ("path",),
                    type="path_outside_root",
                    input=e.path,
                    msg="the path is absolute or escapes the root",
                    hint="use a path relative to the root",
                )
            )
            continue
        if not p.is_file():
            near = [
                f.relative_to(root.resolve()).as_posix()
                for f in root.resolve().rglob(Path(e.path).name)
                if not set(f.relative_to(root.resolve()).parts) & SKIP_DIRS
            ][:5]
            errs.append(
                ErrorDetail(
                    loc=loc + ("path",),
                    type="file_not_found",
                    input=e.path,
                    msg=f"{e.path} does not exist",
                    hint=suggest(e.path, near) or (f"similar files: {near}" if near else "check the indexed paths"),
                )
            )
            continue
        if allowed is not None and e.path not in allowed:
            errs.append(
                ErrorDetail(
                    loc=loc + ("path",),
                    type="file_not_in_context",
                    input=e.path,
                    msg="the file is not part of the selected context",
                    hint=f"edit one of {sorted(allowed)[:6]} or widen the context first",
                )
            )
            continue
        before, current = texts.get(e.path, (None, None))
        if before is None:
            before = current = p.read_text(encoding="utf-8")
        n = current.count(e.old)
        if n != 1:
            if n == 0:
                close = difflib.get_close_matches(
                    e.old.strip().splitlines()[0], [ln.strip() for ln in current.splitlines()], n=1, cutoff=0.6
                )
                hint = f"closest line: {close[0]!r}" if close else "copy the text exactly, including indentation"
                errs.append(
                    ErrorDetail(
                        loc=loc + ("old",),
                        type="old_text_not_found",
                        msg="the text to replace is not in the file",
                        hint=hint,
                    )
                )
            else:
                errs.append(
                    ErrorDetail(
                        loc=loc + ("old",),
                        type="old_text_ambiguous",
                        msg=f"the text occurs {n} times",
                        hint="include neighbouring lines so it is unique",
                    )
                )
            continue
        if e.new == e.old:
            errs.append(ErrorDetail(loc=loc + ("new",), type="no_change", msg="new text equals old text"))
            continue
        texts[e.path] = (before, current.replace(e.old, e.new, 1))
    for path, (before, after) in texts.items():
        if path.endswith(".py"):
            try:
                ast.parse(before)
            except SyntaxError:
                continue  # already broken: do not blame the edit
            try:
                ast.parse(after)
            except SyntaxError as exc:
                errs.append(
                    ErrorDetail(
                        loc=("params", "edits"),
                        type="patch_breaks_syntax",
                        input=path,
                        msg=f"{path} would not parse: line {exc.lineno}: {exc.msg}",
                        hint="make the replacement a complete, balanced statement block",
                    )
                )
    return texts, errs


def _counts(before: str, after: str) -> tuple[int, int]:
    add = dele = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            add += 1
        elif line.startswith("-") and not line.startswith("---"):
            dele += 1
    return add, dele


@component("patch_propose")
class PatchPropose(Component[PatchProposeParams, PatchProposeResult]):
    Params = PatchProposeParams
    Result = PatchProposeResult

    def extra_checks(self, inputs: dict, params: PatchProposeParams) -> list[ErrorDetail]:
        errs = _root_check(params.root)
        if errs:
            return errs
        texts, errs = _apply(params, inputs.get("context"))
        if not errs:
            changed = sum(sum(_counts(b, a)) for b, a in texts.values())
            if changed > params.max_changed_lines:
                errs.append(
                    ErrorDetail(
                        loc=("params", "edits"),
                        type="patch_too_large",
                        msg=f"{changed} changed lines > {params.max_changed_lines}",
                        hint="split the change into smaller, reviewable patches",
                    )
                )
        return errs

    def compute(self, inputs: dict, params: PatchProposeParams, ctx: StepContext) -> PatchProposeResult:
        texts, _ = _apply(params, inputs.get("context"))
        diff, files = [], []
        for path, (before, after) in texts.items():
            diff += list(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            a, d = _counts(before, after)
            files.append(FilePatch(path=path, additions=a, deletions=d))
        ctx.emit("diff", "".join(diff))
        warns = (
            ["no context was bound: edits were not restricted to the selected files"]
            if not inputs.get("context")
            else []
        )
        return PatchProposeResult(
            files=files,
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
            warnings=warns,
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return (
            f"Patch touches {len(r['files'])} file(s): +{r['additions']} -{r['deletions']} (not applied).",
            [f"{f['path']}: +{f['additions']} -{f['deletions']}" for f in r["files"]],
        )


__all__ = [
    "CodeReview",
    "CodeReviewParams",
    "CodeReviewResult",
    "ContextPack",
    "ContextPackParams",
    "ContextPackResult",
    "ContextSelect",
    "ContextSelectParams",
    "ContextSelectResult",
    "Edit",
    "FilePatch",
    "Finding",
    "LargeFile",
    "PatchPropose",
    "PatchProposeParams",
    "PatchProposeResult",
    "RepoIndex",
    "RepoIndexParams",
    "RepoIndexResult",
    "SelectedFile",
]
