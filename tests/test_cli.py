"""agent-fabric CLI: subcommands share the same loaders; rich renders are tested headless."""

import io
import json

import pytest
from rich.console import Console

from agent_fabric.cli import build_parser, main
from agent_fabric.cli.commands import _load_input, cmd_agents, cmd_catalog, cmd_lint, cmd_run
from agent_fabric.llm.backends import ScriptedBackend

NOTES = "config/notes"
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
