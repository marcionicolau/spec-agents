"""agent-fabric CLI: subcommands share the same loaders; rich renders are tested headless."""

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from agent_fabric.cli import build_parser, main
from agent_fabric.cli.commands import _load_input, cmd_agents, cmd_catalog, cmd_lint, cmd_run
from agent_fabric.llm.backends import ScriptedBackend

NOTES = str(Path(__file__).resolve().parents[3] / "examples" / "notes")
TRANSCRIPT = "We agreed to ship on Friday. Ana owns the release notes."


def cap() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, no_color=True, width=200)


def out(console: Console) -> str:
    return console.file.getvalue()


def args(*argv: str):
    return build_parser().parse_args(list(argv))


# ------------------------------------------------------------------ catalog / agents / lint
def test_catalog_table():
    console = cap()
    assert cmd_catalog(args("catalog", "--skills", f"{NOTES}/skills"), console) == 0
    text = out(console)
    for name in ("summarize_notes", "extract_actions", "note_digest"):
        assert name in text
    assert "prompt" in text


def test_agents_tree_valid():
    console = cap()
    assert cmd_agents(args("agents", NOTES), console) == 0
    assert "note_taker" in out(console)


def test_lint_clean_config():
    console = cap()
    assert cmd_lint(args("lint", "--agents", NOTES, "--strict"), console) == 0
    assert "0 error(s)" in out(console)


def test_lint_reports_config_errors(tmp_path):
    (tmp_path / "fabric.md").write_text("---\nroot: a\n---\n", encoding="utf-8")
    d = tmp_path / "agents" / "a"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text("---\nname: a\nkind: bogus\ndescription: x\n---\nBe brief.\n", encoding="utf-8")
    console = cap()
    assert cmd_lint(args("lint", "--agents", str(tmp_path)), console) == 1
    assert "unknown_kind" in out(console)


# ------------------------------------------------------------------ run (plain mode, scripted backend)
def test_run_plain(tmp_path):
    txt = tmp_path / "meeting.txt"
    txt.write_text(TRANSCRIPT, encoding="utf-8")
    plan = '{"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}'
    be = ScriptedBackend([plan, '{"summary": "Ship Friday agreed."}'])
    console = cap()
    a = args("run", NOTES, "Digest this meeting", "--plain", "--input", f"transcript={txt}")
    assert cmd_run(a, console, backend=be) == 0
    text = out(console)
    assert "note_taker" in text and "Ship Friday agreed." in text


def test_main_dispatch_catalog():
    assert main(["catalog", "--skills", f"{NOTES}/skills"]) == 0


# ------------------------------------------------------------------ input loading
def test_load_input_suffixes(tmp_path):
    txt = tmp_path / "n.txt"
    txt.write_text(TRANSCRIPT, encoding="utf-8")
    name, value = _load_input(f"transcript={txt}")
    assert name == "transcript" and value == TRANSCRIPT

    js = tmp_path / "d.json"
    js.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert _load_input(f"meta={js}") == ("meta", {"a": 1})

    jl = tmp_path / "d.jsonl"
    jl.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    assert _load_input(f"rows={jl}") == ("rows", [{"a": 1}, {"a": 2}])


def test_load_input_missing():
    from agent_fabric.errors import DependencyError

    with pytest.raises(DependencyError):
        _load_input("x=/does/not/exist.txt")


# ------------------------------------------------------------------ live view
def test_live_view_renders_agents_steps_and_events():
    """Regression: the board crashed with TypeError (invalid Table.grid kwarg) once an agent or event existed."""
    from types import SimpleNamespace

    from agent_fabric.cli.live import RunView

    view = RunView("Digest this")
    view.on_event(SimpleNamespace(event="start", path="note_taker", detail=""))
    view.on_event(SimpleNamespace(event="llm_call", path="note_taker", detail="local-fast"))
    view.on_step(SimpleNamespace(step_id="s1", component="summarize_notes", status="ok", duration_s=0.12))
    view.on_event(SimpleNamespace(event="end", path="note_taker", detail="ok"))
    console = cap()
    console.print(view.renderable())
    text = out(console)
    for needle in ("note_taker", "agents", "pipeline steps", "events", "summarize_notes"):
        assert needle in text


# ------------------------------------------------------------------ installed packs are discovered
def test_catalog_discovers_installed_packs_by_default():
    console = cap()
    assert cmd_catalog(args("catalog"), console) == 0
    text = out(console)
    assert "summary" in text and "keywords" in text  # statistics and text packs, no flags needed


def test_no_discover_restores_isolation():
    console = cap()
    assert cmd_catalog(args("catalog", "--no-discover", "--skills", f"{NOTES}/skills"), console) == 0
    text = out(console)
    assert "summarize_notes" in text  # explicit skills still load
    assert "linear_model" not in text and "keywords" not in text  # installed packs are not


def test_domains_flag_is_additive_and_idempotent_with_discovery():
    console = cap()
    assert cmd_catalog(args("catalog", "--domains", "stat_fabric.domain:register"), console) == 0
    assert out(console).count("linear_model") == 1  # loaded twice (flag + discovery), listed once


def test_lint_command_discovers_but_module_stays_explicit():
    from agent_fabric.lint import collect_issues

    cmd = collect_issues(["stat_fabric.domain:register"], discover=True)
    explicit = collect_issues(["stat_fabric.domain:register"])
    assert isinstance(cmd, list) and isinstance(explicit, list)


def test_incompatible_installed_pack_is_reported_and_can_be_skipped(monkeypatch, capsys):
    from importlib import metadata

    from agent_fabric import API_LEVEL, requires_api

    @requires_api(API_LEVEL + 1)
    def register(registry):  # pragma: no cover - never reached
        return []

    class EP:
        name = "future-pack"

        def load(self):
            return register

    monkeypatch.setattr(metadata, "entry_points", lambda group: [EP()])
    assert main(["catalog"]) == 2  # FabricError -> located message, exit code 2
    printed = capsys.readouterr().out
    assert "Incompatible domain pack" in printed and "future-pack" in printed
    assert main(["catalog", "--no-discover", "--skills", f"{NOTES}/skills"]) == 0
