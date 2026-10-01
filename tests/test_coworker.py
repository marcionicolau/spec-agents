"""Coworker domain: repo index, context selection, review and validated patches."""

import json
import os
import textwrap

import pytest

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from coworker_fabric.domain import register as register_coworker

FILES = {
    "src/shop/__init__.py": "",
    "src/shop/orders.py": '''
        from . import pricing
        from .util import fmt
        import os


        def total(items, extra=[]):
            """Order total."""
            try:
                return pricing.apply(sum(i.price for i in items))
            except:
                return 0  # TODO handle currency


        def render(order):
            print(fmt(order))
    ''',
    "src/shop/pricing.py": """
        def apply(amount, rate=0.2):
            return amount * (1 + rate)
    """,
    "src/shop/util.py": """
        def fmt(x):
            return str(x)
    """,
    "src/shop/unrelated.py": """
        class Weather:
            def forecast(self):
                return "sunny"
    """,
    "tests/test_orders.py": """
        from shop.orders import total

        def test_total():
            assert total([]) == 0
    """,
    "README.md": "# shop",
}


@pytest.fixture(scope="module")
def cw():
    return build_registry([register_coworker])


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_ALLOWED_ROOTS", str(tmp_path))
    for rel, body in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body).lstrip("\n"))
    return tmp_path


def run(cw, name, params):
    spec = cw.pipeline(name)
    pin = PipelineInputs.from_values({}, cw.types)
    return PipelineExecutor(cw).run(parse_plan(spec.instantiate(params), cw, pin), pin)


def errors(rep):
    return {(".".join(map(str, d.loc)), d.type): d for o in rep.outcomes if o.error for d in o.error.details}


def test_domain_registered(cw):
    assert {"repo_index", "context_select", "context_pack", "code_review", "patch_propose"} <= set(cw.names())
    assert {"improve_code", "propose_patch"} <= set(cw.pipelines())


def test_index_builds_import_graph(cw, repo):
    rep = run(
        cw, "improve_code", {"root": str(repo), "task": "fix order totals", "focus_files": ["src/shop/orders.py"]}
    )
    assert rep.ok, errors(rep)
    idx = rep.by_id("index").result
    assert idx["n_python"] == 6 and idx["n_symbols"] >= 5
    assert idx["n_edges"] == 3  # orders->pricing, orders->util, test->orders


def test_context_prefers_neighbours_and_tests_over_unrelated(cw, repo):
    rep = run(
        cw, "improve_code", {"root": str(repo), "task": "fix order totals", "focus_files": ["src/shop/orders.py"]}
    )
    sel = {s["path"]: s for s in rep.by_id("pick").result["selected"]}
    assert (
        sel["src/shop/orders.py"]["reasons"] == ["focus file", "matches task terms: orders"]
        or "focus file" in sel["src/shop/orders.py"]["reasons"]
    )
    assert {"src/shop/pricing.py", "src/shop/util.py", "tests/test_orders.py"} <= set(sel)
    assert "src/shop/unrelated.py" not in sel
    assert "test of a focus file" in sel["tests/test_orders.py"]["reasons"]
    out = rep.output_values()
    assert "## src/shop/orders.py" in out["bundle"] and "def total" in out["bundle"]


def test_token_budget_and_term_only_selection(cw, repo):
    rep = run(cw, "improve_code", {"root": str(repo), "task": "weather forecast", "token_budget": 200})
    assert rep.ok, errors(rep)
    assert [s["path"] for s in rep.by_id("pick").result["selected"]] == ["src/shop/unrelated.py"]
    with (repo / "src/shop/orders.py").open("a") as fh:
        fh.write("# padding\n" * 200)
    tiny = run(
        cw,
        "improve_code",
        {"root": str(repo), "task": "fix order totals", "focus_files": ["src/shop/orders.py"], "token_budget": 200},
    )
    assert ("params.token_budget", "focus_exceeds_budget") in errors(tiny)


def test_selection_errors_are_located(cw, repo):
    rep = run(cw, "improve_code", {"root": str(repo), "task": "fix things", "focus_files": ["src/shop/order.py"]})
    assert "src/shop/orders.py" in errors(rep)[("params.focus_files.0", "file_not_in_index")].hint
    vague = run(cw, "improve_code", {"root": str(repo), "task": "make it so"})
    assert ("params.task", "task_too_vague") in errors(vague)
    missing = run(cw, "improve_code", {"root": str(repo / "nope"), "task": "orders"})
    assert ("params.root", "root_not_found") in errors(missing)


def test_review_finds_real_problems(cw, repo):
    rep = run(
        cw, "improve_code", {"root": str(repo), "task": "fix order totals", "focus_files": ["src/shop/orders.py"]}
    )
    rules = {(f["rule"], f["path"]) for f in rep.output_values()["findings"]}
    assert {
        ("mutable_default", "src/shop/orders.py"),
        ("bare_except", "src/shop/orders.py"),
        ("unused_import", "src/shop/orders.py"),
        ("print_call", "src/shop/orders.py"),
        ("todo_comment", "src/shop/orders.py"),
    } <= rules
    assert ("unused_import", "src/shop/pricing.py") not in rules
    sev = [f["severity"] for f in rep.output_values()["findings"]]
    assert sev == sorted(sev, key=["error", "warning", "info"].index)  # most severe first
    json.dumps(rep.model_dump(mode="json"))


def test_patch_valid_diff_and_nothing_written(cw, repo):
    before = (repo / "src/shop/orders.py").read_text()
    rep = run(
        cw,
        "propose_patch",
        {
            "root": str(repo),
            "task": "fix mutable default in total",
            "focus_files": ["src/shop/orders.py"],
            "edits": [
                {
                    "path": "src/shop/orders.py",
                    "old": "def total(items, extra=[]):",
                    "new": "def total(items, extra=None):",
                }
            ],
        },
    )
    assert rep.ok, errors(rep)
    diff = rep.output_values()["diff"]
    assert "--- a/src/shop/orders.py" in diff and "+def total(items, extra=None):" in diff
    assert (repo / "src/shop/orders.py").read_text() == before


def test_patch_errors_are_specific(cw, repo):
    def attempt(**edit):
        return errors(
            run(
                cw,
                "propose_patch",
                {
                    "root": str(repo),
                    "task": "change orders",
                    "focus_files": ["src/shop/orders.py"],
                    "edits": [{"path": "src/shop/orders.py", **edit}],
                },
            )
        )

    e = attempt(old="def totl(items, extra=[]):", new="x")
    assert "def total" in e[("params.edits.0.old", "old_text_not_found")].hint
    assert ("params.edits.0.old", "old_text_ambiguous") in attempt(old="    ", new="  ")
    assert ("params.edits", "patch_breaks_syntax") in attempt(
        old="def total(items, extra=[]):", new="def total(items, extra=[]"
    )
    assert ("params.edits.0.new", "no_change") in attempt(old="return 0", new="return 0")
    out = errors(
        run(
            cw,
            "propose_patch",
            {
                "root": str(repo),
                "task": "change orders",
                "focus_files": ["src/shop/orders.py"],
                "edits": [
                    {"path": "../evil.py", "old": "a", "new": "b"},
                    {"path": "src/shop/util.py", "old": "str(x)", "new": "repr(x)"},
                    {"path": "src/shop/unrelated.py", "old": "sunny", "new": "rainy"},
                ],
            },
        )
    )
    assert ("params.edits.0.path", "path_outside_root") in out
    assert ("params.edits.2.path", "file_not_in_context") in out and (
        "params.edits.1.path",
        "file_not_in_context",
    ) not in out


def test_patch_size_limit(cw, repo):
    big = "\n".join(f"    x{i} = {i}" for i in range(30))
    rep = run(
        cw,
        "propose_patch",
        {
            "root": str(repo),
            "task": "change orders",
            "focus_files": ["src/shop/orders.py"],
            "max_changed_lines": 5,
            "edits": [
                {
                    "path": "src/shop/orders.py",
                    "old": "    return 0  # TODO handle currency",
                    "new": big + "\n    return 0",
                }
            ],
        },
    )
    assert ("params.edits", "patch_too_large") in errors(rep)


def test_pair_programmer_team_with_patch_repair(cw, repo):
    from pathlib import Path

    from agent_fabric.agents import AgentFabric, AgentsConfig
    from agent_fabric.llm import ScriptedBackend
    from coworker_fabric.schemas import Critique

    root = str(repo)
    base = {"root": root, "task": "fix the mutable default in total", "focus_files": ["src/shop/orders.py"]}
    route = {
        "rationale": "scout first",
        "delegations": [
            {"id": "d1", "agent": "context_scout", "instruction": "pick the context for order totals", "inputs": []},
            {
                "id": "d2",
                "agent": "code_critic",
                "instruction": "prioritise the findings",
                "inputs": ["@d1"],
                "depends_on": ["d1"],
            },
            {
                "id": "d3",
                "agent": "patch_author",
                "instruction": "fix the mutable default",
                "inputs": ["@d1"],
                "depends_on": ["d1"],
            },
        ],
    }
    scout_plan = cw.pipeline("improve_code").instantiate(
        {"root": root, "task": "order totals", "focus_files": ["src/shop/orders.py"]}
    )
    scout_plan["objective"] = "Pick the context for order totals"
    critique = {
        "summary": "The total function has a mutable default and a bare except.",
        "suggestions": [
            {"path": "src/shop/orders.py", "priority": "high", "change": "Use None as the default for extra."}
        ],
    }
    good_edit = {
        "path": "src/shop/orders.py",
        "old": "def total(items, extra=[]):",
        "new": "def total(items, extra=None):",
    }
    bad_plan = cw.pipeline("propose_patch").instantiate(
        {**base, "edits": [{**good_edit, "old": "def totl(items, extra=[]):"}]}
    )
    bad_plan["objective"] = "Fix the mutable default"
    repaired = {"params": {"root": root, "edits": [good_edit]}}
    backend = ScriptedBackend(
        [
            json.dumps(route),
            json.dumps(scout_plan),
            json.dumps(critique),
            json.dumps(bad_plan),
            json.dumps(repaired),
            "Replace the default with None; the patch validates and was not applied.",
        ]
    )
    fabric = AgentFabric(
        cw, AgentsConfig.load(Path(__file__).resolve().parents[1] / "config" / "coworker"), backend=backend
    )
    fabric.register_schema("Critique", Critique)
    assert not fabric.validate()
    rep = fabric.run("Improve order totals in " + root, session_id="cw")
    assert rep.ok, rep.result.tree()
    assert [c.agent for c in rep.result.children] == ["context_scout", "code_critic", "patch_author"]
    diff = json.dumps(rep.result.find("patch_author").output)
    assert "extra=None" in diff
    assert "extra=[]" in (repo / "src/shop/orders.py").read_text()  # never written
    assert "old_text_not_found" in json.dumps(backend.calls[4]["messages"])  # the repairer saw the located error


def test_roots_outside_the_allowlist_are_rejected(cw, repo, monkeypatch, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (elsewhere / "secret.py").write_text("x = 1\n")
    for root in (str(elsewhere), "/etc", str(repo / "..")):
        rep = run(cw, "improve_code", {"root": root, "task": "orders"})
        assert ("params.root", "root_not_allowed") in errors(rep), root
    patch = run(
        cw,
        "propose_patch",
        {
            "root": str(elsewhere),
            "task": "secret",
            "focus_files": ["secret.py"],
            "edits": [{"path": "secret.py", "old": "x = 1", "new": "x = 2"}],
        },
    )
    assert ("params.root", "root_not_allowed") in errors(patch)
    monkeypatch.setenv("COWORKER_ALLOWED_ROOTS", f"{repo}{os.pathsep}{elsewhere}")  # explicit opt-in
    assert ("params.root", "root_not_allowed") not in errors(
        run(cw, "improve_code", {"root": str(elsewhere), "task": "secret"})
    )


def test_default_root_is_the_working_directory(cw, repo, monkeypatch, tmp_path_factory):
    monkeypatch.delenv("COWORKER_ALLOWED_ROOTS")
    monkeypatch.chdir(repo)
    assert run(
        cw, "improve_code", {"root": str(repo), "task": "fix order totals", "focus_files": ["src/shop/orders.py"]}
    ).ok
    monkeypatch.chdir(tmp_path_factory.mktemp("other"))
    assert ("params.root", "root_not_allowed") in errors(run(cw, "improve_code", {"root": str(repo), "task": "orders"}))


# --------------------------------------------------------------------------- context quality
def test_context_selection_quality_on_this_repository(cw, monkeypatch):
    """Regression guard on the labeled cases: tuning the scorer must not lose recall or ranking."""
    from pathlib import Path

    from coworker_fabric.evals import load_cases, run_cases

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("COWORKER_ALLOWED_ROOTS", str(root))
    cases = load_cases(root / "examples" / "evals" / "context_cases.yaml")
    missing = [p for c in cases for p in c.expected if not (root / p).exists()]
    assert not missing, f"cases reference files that no longer exist: {missing}"
    scores = run_cases(root, cases, token_budget=6000, max_files=8, relative_cutoff=0.5)
    n = len(scores)
    assert sum(s.recall for s in scores) / n >= 0.95, [(s.name, s.missing) for s in scores if s.missing]
    assert sum(s.score for s in scores) / n >= 0.92
    assert sum(s.precision for s in scores) / n >= 0.4
    assert all(s.first_hit_rank == 1 for s in scores)


BIG = "\n".join(
    ["import os", "", ""]
    + [
        f'def parse_invoice_{i}(text):\n    """Parse an invoice line."""\n    return text.split(\',\')[{i}]\n\n'
        for i in range(40)
    ]
    + [
        'def convert_currency(amount, rate=[]):\n    """Convert money between currencies using an exchange rate."""\n    return amount * rate\n\n',
        "def format_exchange(rate):\n    return f'{rate:.4f}'\n",
    ]
)


def test_large_files_contribute_only_their_matching_symbols(cw, repo):
    (repo / "src/shop/billing.py").write_text(BIG)
    (repo / "src/shop/notes.py").write_text("def note():\n    return 'exchange'\n")
    rep = run(
        cw, "improve_code", {"root": str(repo), "task": "fix the currency exchange conversion", "token_budget": 800}
    )
    assert rep.ok, errors(rep)
    sel = {s["path"]: s for s in rep.by_id("pick").result["selected"]}
    part = sel["src/shop/billing.py"]
    assert (
        part["ranges"]
        and {"convert_currency", "format_exchange"} <= set(part["symbols"])
        and "parse_invoice_3" not in part["symbols"]
    )
    assert (
        part["tokens"]
        < 800
        < next(f["tokens"] for f in rep.by_id("index").result["largest"] if f["path"] == "src/shop/billing.py")
    )
    bundle = rep.output_values()["bundle"]
    assert "def convert_currency" in bundle and "parse_invoice_7" not in bundle and "# --- lines" in bundle
    rules = [(f["rule"], f["path"]) for f in rep.output_values()["findings"]]
    assert ("mutable_default", "src/shop/billing.py") in rules  # inside the selected range
    whole = run(
        cw, "improve_code", {"root": str(repo), "task": "fix the currency exchange conversion", "token_budget": 800}
    )
    assert ("missing_return_annotation", "src/shop/billing.py") in [
        (f["rule"], f["path"]) for f in whole.output_values()["findings"]
    ]
    outside = [
        f
        for f in rep.output_values()["findings"]
        if f["path"] == "src/shop/billing.py"
        and f["rule"] == "missing_return_annotation"
        and not any(a <= f["line"] <= b for a, b in part["ranges"])
    ]
    assert not outside  # findings outside the ranges are not reported


def test_partial_files_can_be_switched_off(cw, repo):
    (repo / "src/shop/billing.py").write_text(BIG)
    task = {"root": str(repo), "task": "fix the currency exchange conversion", "token_budget": 800}
    on = run(cw, "improve_code", task)
    assert "src/shop/billing.py" in {s["path"] for s in on.by_id("pick").result["selected"]}
    pin = PipelineInputs.from_values({}, cw.types)
    plan = parse_plan({**cw.pipeline("improve_code").instantiate(task), "objective": "no partial files"}, cw, pin)
    plan.steps[1].params["partial_files"] = False
    off = PipelineExecutor(cw).run(plan, pin)
    assert "src/shop/billing.py" not in {
        s["path"] for s in off.by_id("pick").result.get("selected", [])
    }  # too big as a whole


def test_rare_words_outweigh_common_ones_and_tests_rank_lower(cw, repo):
    for i in range(6):  # "order" is everywhere, "refund" is in one file only
        (repo / f"src/shop/mod{i}.py").write_text(f"def order_{i}():\n    return 'order'\n")
    (repo / "src/shop/payments.py").write_text("def process_refund(order):\n    return order\n")
    (repo / "tests/test_payments.py").write_text(
        "def test_refund():\n    assert process_refund(1)\n" + "# refund\n" * 40
    )
    rep = run(cw, "improve_code", {"root": str(repo), "task": "handle refund of an order"})
    ranked = [s["path"] for s in rep.by_id("pick").result["selected"]]
    assert ranked[0] == "src/shop/payments.py"
    if "tests/test_payments.py" in ranked:
        assert ranked.index("tests/test_payments.py") > 0
    asks_tests = run(cw, "improve_code", {"root": str(repo), "task": "add a test for the refund of an order"})
    assert "tests/test_payments.py" in [s["path"] for s in asks_tests.by_id("pick").result["selected"]]
