"""Pure, deterministic code analysis used by the coworker components (Python ``ast`` only)."""

from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", ".hg", ".venv", "venv", "env", "node_modules", "__pycache__", "build", "dist", ".mypy_cache",
             ".ruff_cache", ".pytest_cache", ".tox", ".eggs", "site-packages"}
_BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "into", "code", "file", "files", "function", "class",
             "make", "add", "fix", "improve", "refactor", "use", "using", "should", "when", "have", "not", "are"}


def token_estimate(text: str) -> int:
    return (len(text) + 3) // 4


def module_name(rel: str) -> str:
    parts = list(Path(rel).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def complexity(node: ast.AST) -> int:
    total = 1
    for n in ast.walk(node):
        if isinstance(n, _BRANCH):
            total += 1
        elif isinstance(n, ast.BoolOp):
            total += len(n.values) - 1
        elif hasattr(ast, "match_case") and isinstance(n, ast.match_case):
            total += 1
    return total


def words(text: str) -> list[str]:
    """Search terms from prose or identifiers: splits snake_case and camelCase, drops stop words."""
    out: list[str] = []
    for w in _WORD.findall(text):
        for part in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", w).lower().split("_"):
            if len(part) >= 3 and part not in STOPWORDS and part not in out:
                out.append(part)
    return out


def stem(word: str) -> str:
    """Crude stem: drop a plural 's' and keep six letters, so delegate/delegation/delegating and dependent/dependencies meet."""
    w = word.lower()
    if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w[:6]


def stems(text: str) -> list[str]:
    return [stem(w) for w in words(text)]


def _vocab(node: ast.AST, top: int) -> dict[str, int]:
    """Stemmed word counts of the identifiers, docstrings and short messages under ``node``."""
    counts: dict[str, int] = {}

    def add(text: str) -> None:
        for st in stems(text):
            counts[st] = counts.get(st, 0) + 1

    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            add(n.id)
        elif isinstance(n, ast.Attribute):
            add(n.attr)
        elif isinstance(n, ast.arg):
            add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(n.name)
            doc = ast.get_docstring(n)
            if doc:
                add(doc[:400])
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and 3 <= len(n.value) <= 120:
            add(n.value)
        elif isinstance(n, ast.Module):
            doc = ast.get_docstring(n)
            if doc:
                add(doc[:400])
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:top])


def analyse_python(source: str) -> dict[str, Any]:
    """Symbols (functions, classes, methods) and raw imports of one module, or ``{"error": ...}``."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"error": f"line {exc.lineno}: {exc.msg}", "symbols": [], "imports": [], "terms": {}}
    symbols: list[dict[str, Any]] = []
    lines = source.splitlines()

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{node.name}"
                is_class = isinstance(node, ast.ClassDef)
                end = node.end_lineno or node.lineno
                sym: dict[str, Any] = {"name": name, "kind": "class" if is_class else "function", "line": node.lineno,
                                       "end_line": end, "tokens": token_estimate("\n".join(lines[node.lineno - 1:end])),
                                       "terms": _vocab(node, 25)}
                if not is_class:
                    a = node.args
                    n_params = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs) + bool(a.vararg) + bool(a.kwarg)
                    if prefix and a.args and a.args[0].arg in ("self", "cls"):
                        n_params -= 1
                    sym.update(complexity=complexity(node), n_params=n_params, returns_annotated=node.returns is not None)
                symbols.append(sym)
                visit(node.body, f"{name}.")
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                for block in (getattr(node, "body", []), getattr(node, "orelse", []), getattr(node, "finalbody", [])):
                    visit(block, prefix)

    visit(tree.body, "")
    imports: list[list[Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [[a.name, 0, None] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports += [[node.module or "", node.level, a.name] for a in node.names]
    return {"symbols": symbols, "imports": imports, "terms": _vocab(tree, 120)}


def resolve_import(mod: str, level: int, name: str | None, current: str, is_package: bool, modules: set[str]) -> str | None:
    """Module name (present in ``modules``) that an import statement refers to, longest match wins."""
    if level:
        pkg = current.split(".") if is_package else current.split(".")[:-1]
        pkg = pkg[: len(pkg) - (level - 1)] if level > 1 else pkg
        base = ".".join(pkg + ([mod] if mod else []))
    else:
        base = mod
    candidates = [f"{base}.{name}"] if name and base else []
    candidates += [base] if base else []
    for cand in candidates:
        parts = cand.split(".")
        for i in range(len(parts), 0, -1):
            m = ".".join(parts[:i])
            if m in modules and m != current:
                return m
    return None


def review_source(rel: str, source: str, *, max_function_lines: int, max_complexity: int, max_params: int) -> list[dict[str, Any]]:
    """Static findings for one Python file. Each: {path, line, rule, severity, message, suggestion}."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [_f(rel, exc.lineno or 1, "syntax_error", "error", exc.msg, "fix the syntax before anything else")]
    out: list[dict[str, Any]] = []
    is_test = "tests" in Path(rel).parts or Path(rel).name.startswith("test_")
    is_init = Path(rel).name == "__init__.py"

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > max_function_lines:
                out.append(_f(rel, node.lineno, "long_function", "warning", f"{node.name} spans {length} lines (max {max_function_lines})",
                              "extract cohesive blocks into helpers"))
            cx = complexity(node)
            if cx > max_complexity:
                out.append(_f(rel, node.lineno, "high_complexity", "warning", f"{node.name} has complexity {cx} (max {max_complexity})",
                              "split branches into functions or use early returns"))
            a = node.args
            n = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs) - (1 if a.args and a.args[0].arg in ("self", "cls") else 0)
            if n > max_params:
                out.append(_f(rel, node.lineno, "many_params", "info", f"{node.name} takes {n} parameters (max {max_params})",
                              "group related parameters into a dataclass or model"))
            for d in list(a.defaults) + [d for d in a.kw_defaults if d is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)) or (isinstance(d, ast.Call) and _name(d.func) in ("list", "dict", "set")):
                    out.append(_f(rel, d.lineno, "mutable_default", "error", f"{node.name} has a mutable default argument",
                                  "default to None and create the value inside the function"))
            if not node.name.startswith("_") and node.returns is None and not is_test:
                out.append(_f(rel, node.lineno, "missing_return_annotation", "info", f"public function {node.name} has no return annotation",
                              "annotate the return type"))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                out.append(_f(rel, node.lineno, "bare_except", "warning", "bare 'except:' also catches KeyboardInterrupt and SystemExit",
                              "catch the specific exception types you expect"))
            elif _name(node.type) in ("Exception", "BaseException") and all(isinstance(s, ast.Pass) for s in node.body):
                out.append(_f(rel, node.lineno, "swallowed_exception", "warning", f"'except {_name(node.type)}: pass' hides failures",
                              "handle, log or re-raise the error"))
        elif isinstance(node, ast.Call):
            fn = _name(node.func)
            if fn in ("eval", "exec"):
                out.append(_f(rel, node.lineno, "eval_exec", "error", f"call to {fn}()", "use ast.literal_eval or an explicit dispatch table"))
            elif fn == "print" and not is_test and Path(rel).name != "__main__.py":
                out.append(_f(rel, node.lineno, "print_call", "info", "print() in library code", "use the logging module"))

    if not is_init:
        imported: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for al in node.names:
                    imported[(al.asname or al.name).split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                for al in node.names:
                    if al.name != "*":
                        imported[al.asname or al.name] = node.lineno
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        exported = {c.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(_name(t) == "__all__" for t in n.targets)
                    for c in ast.walk(n.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        text_refs = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", " ".join(
            c.value for c in ast.walk(tree) if isinstance(c, ast.Constant) and isinstance(c.value, str))))
        for name, line in sorted(imported.items(), key=lambda kv: kv[1]):
            if name not in used and name not in exported and name not in text_refs:
                out.append(_f(rel, line, "unused_import", "warning", f"'{name}' is imported but never used", "remove the import"))

    for i, line in enumerate(source.splitlines(), 1):
        m = re.search(r"#\s*(TODO|FIXME|XXX)\b(.*)", line)
        if m:
            out.append(_f(rel, i, "todo_comment", "info", f"{m.group(1)}{m.group(2).strip()[:80]}", "resolve it or link an issue"))
    return out


def _name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def _f(path: str, line: int, rule: str, severity: str, message: str, suggestion: str) -> dict[str, Any]:
    return {"path": path, "line": line, "rule": rule, "severity": severity, "message": message, "suggestion": suggestion}


def safe_path(root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` under ``root``; None when it escapes the root (``..``, absolute path, symlink)."""
    if not rel or Path(rel).is_absolute():
        return None
    p = (root / rel).resolve()
    return p if p.is_relative_to(root.resolve()) else None


ROOTS_ENV = "COWORKER_ALLOWED_ROOTS"


def allowed_roots() -> list[Path]:
    """Directories the coworker may read: ``$COWORKER_ALLOWED_ROOTS`` (os.pathsep-separated) or the working directory."""
    raw = os.environ.get(ROOTS_ENV, "")
    roots = [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
    return roots or [Path.cwd().resolve()]


def root_allowed(root: str | Path) -> bool:
    """True when ``root`` is one of the allowed roots or lies inside one (a plan cannot point the index at ``/etc``)."""
    resolved = Path(root).expanduser().resolve()
    return any(resolved.is_relative_to(r) for r in allowed_roots())


# ---------------------------------------------------------------------------- relevance scoring
class Scorer:
    """BM25-flavoured relevance of files and symbols to a task, with IDF computed over the indexed files.

    A word that appears in most files ("agent", "source") says little; a rare one ("delegation") says a lot.
    Matches in a path weigh three times, in a symbol name twice, in the body once.
    """

    K = 1.2

    def __init__(self, files: list[dict[str, Any]], task: str) -> None:
        import math

        self.terms = words(task)
        self.stem_of = {stem(t): t for t in self.terms}
        py = [f for f in files if f.get("terms")]
        n = max(len(py), 1)
        df: dict[str, int] = defaultdict(int)
        for f in files:
            seen = set(f.get("terms", {})) | set(stems(f["path"])) | {w for s in f["symbols"] for w in stems(s["name"])}
            for st in seen & set(self.stem_of):
                df[st] += 1
        self.idf = {st: math.log(1 + (n - df[st] + 0.5) / (df[st] + 0.5)) for st in self.stem_of if df[st] > 0}
        self.total = sum(self.idf.values()) or 1.0
        self.avg_tokens = sum(f["tokens"] for f in files) / max(len(files), 1) or 1.0

    def _score(self, counts: dict[str, int], path_stems: set[str], name_stems: set[str], tokens: int, norm: float = 1.0) -> tuple[float, list[str]]:
        total, hits = 0.0, []
        length = 0.25 + 0.75 * (tokens / self.avg_tokens) * norm
        for st, idf in self.idf.items():
            tf = counts.get(st, 0) + (3 if st in path_stems else 0) + (2 if st in name_stems else 0)
            if tf:
                total += idf * tf / (tf + self.K * length)
                hits.append(self.stem_of[st])
        return min(1.0, total / self.total), hits

    def file(self, f: dict[str, Any]) -> tuple[float, list[str]]:
        names = {w for s in f["symbols"] for w in stems(s["name"])}
        return self._score(f.get("terms", {}), set(stems(f["path"])), names, f["tokens"])

    def symbol(self, sym: dict[str, Any], f: dict[str, Any]) -> tuple[float, list[str]]:
        return self._score(sym.get("terms", {}), set(), set(stems(sym["name"])), int(self.avg_tokens))


def pick_symbols(f: dict[str, Any], scorer: Scorer, budget_tokens: int, preamble_lines: int = 25) -> tuple[list[list[int]], list[str], int] | None:
    """Best-matching symbols of a large file as merged line ranges: (ranges, symbol names, tokens) or None."""
    scored = []
    for sym in f["symbols"]:
        sc, hits = scorer.symbol(sym, f)
        if sc > 0 and hits:
            scored.append((sc, sym))
    if not scored:
        return None
    head = min(max(f["symbols"][0]["line"] - 1, 0), preamble_lines) if f["symbols"] else 0
    used, chosen = head * 12, []
    for sc, sym in sorted(scored, key=lambda t: (-t[0], t[1]["tokens"])):
        if any(c["line"] <= sym["line"] and sym["end_line"] <= c["end_line"] for c in chosen):
            continue  # already inside a chosen symbol
        chosen = [c for c in chosen if not (sym["line"] <= c["line"] and c["end_line"] <= sym["end_line"])]  # swallow contained ones
        if used + sym["tokens"] > budget_tokens:
            continue
        chosen.append(sym)
        used = head * 12 + sum(c["tokens"] for c in chosen)
    if not chosen:
        return None
    spans = sorted([c["line"], c["end_line"]] for c in chosen)
    if head:
        spans.insert(0, [1, head])
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged, [c["name"] for c in sorted(chosen, key=lambda c: c["line"])], used
