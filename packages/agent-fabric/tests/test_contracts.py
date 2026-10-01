"""SKILL.md contract changes must come with a matching version bump."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_fabric.contracts import bump_level, check, classify, contract_of
from agent_fabric.spec import load_spec

SKILL = """---
name: recap
version: {version}
domain: demo
description: Condense a document into a short faithful recap.
runtime: prompt
params:
  tone: {{ description: tone of the recap, required: false, default: neutral }}
{extra_params}inputs:
  text: {{ type: text }}
{extra_inputs}outputs:
  summary: {{ type: text }}
{extra_outputs}---

# recap

## When to use

When a short recap of a document is needed.

## Instructions

Recap {{inputs.text}} in a {{params.tone}} tone.
"""


def skill(version="1.0.0", params="", inputs="", outputs=""):
    return SKILL.format(version=version, extra_params=params, extra_inputs=inputs, extra_outputs=outputs)


def contract(tmp_path: Path, text: str) -> dict:
    d = tmp_path / "recap"
    d.mkdir(exist_ok=True)
    (d / "SKILL.md").write_text(text)
    return contract_of(load_spec(d / "SKILL.md"))


def level(tmp_path: Path, before: str, after: str) -> str:
    return classify(contract(tmp_path, before), contract(tmp_path, after))[0]


def test_prose_and_version_only_changes_are_not_contract(tmp_path):
    assert level(tmp_path, skill(), skill(version="1.0.1").replace("faithful", "brief")) == "none"


def test_optional_additions_are_minor(tmp_path):
    base = skill()
    assert level(tmp_path, base, skill(params="  top_k: { description: how many, required: false }\n")) == "minor"
    assert level(tmp_path, base, skill(outputs="  notes: { type: text }\n")) == "minor"
    assert level(tmp_path, base, skill(inputs="  style: { type: text, required: false }\n")) == "minor"


def test_breaking_changes_are_major(tmp_path):
    base = skill()
    assert level(tmp_path, base, skill(params="  k: { description: required one, required: true }\n")) == "major"
    assert level(tmp_path, base, skill(inputs="  extra: { type: text }\n")) == "major"  # new required input
    assert level(tmp_path, base, base.replace("summary: { type: text }", "summary: { type: json }")) == "major"
    assert level(tmp_path, base, base.replace("  tone:", "  voice:").replace("params.tone", "params.voice")) == "major"
    assert level(tmp_path, base, base.replace("default: neutral", "default: formal")) == "major"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [("1.0.0", "1.0.1", "none"), ("1.0.0", "1.1.0", "minor"), ("1.2.3", "2.0.0", "major"), ("1.2.0", "1.1.9", "down")],
)
def test_bump_level(old, new, expected):
    assert bump_level(old, new) == expected


# ------------------------------------------------------------------ against git
def git(repo: Path, *args: str) -> None:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, env={**env, "PATH": "/usr/bin:/bin"}
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "skills" / "recap").mkdir(parents=True)
    (tmp_path / "skills" / "recap" / "SKILL.md").write_text(skill())
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def write(repo: Path, text: str) -> None:
    (repo / "skills" / "recap" / "SKILL.md").write_text(text)


def test_unchanged_tree_is_clean(repo):
    assert check(repo, "HEAD") == []


def test_added_param_without_bump_fails_with_minor_passes(repo):
    extra = "  top_k: { description: how many, required: false }\n"
    write(repo, skill(params=extra))
    [issue] = check(repo, "HEAD")
    assert issue.severity == "error"
    assert "minor" in issue.msg
    assert "param 'top_k' added" in issue.msg
    write(repo, skill(version="1.1.0", params=extra))
    assert check(repo, "HEAD") == []
    write(repo, skill(version="2.0.0", params=extra))  # a bigger bump is always accepted
    assert check(repo, "HEAD") == []


def test_removed_port_requires_major(repo):
    write(
        repo,
        skill()
        .replace("inputs:\n  text: { type: text }\n", "inputs:\n  other: { type: text, required: false }\n")
        .replace("{inputs.text}", "{inputs.other}"),
    )
    assert any("major" in i.msg for i in check(repo, "HEAD"))
    minor_only = (
        skill(version="1.1.0")
        .replace("inputs:\n  text: { type: text }\n", "inputs:\n  other: { type: text, required: false }\n")
        .replace("{inputs.text}", "{inputs.other}")
    )
    write(repo, minor_only)
    assert any(i.severity == "error" for i in check(repo, "HEAD"))


def test_new_skill_needs_no_bump_and_removed_skill_is_a_notice(repo):
    (repo / "skills" / "other").mkdir()
    (repo / "skills" / "other" / "SKILL.md").write_text(skill().replace("name: recap", "name: other"))
    assert check(repo, "HEAD") == []
    (repo / "skills" / "recap" / "SKILL.md").unlink()
    [issue] = check(repo, "HEAD")
    assert issue.severity == "notice"
