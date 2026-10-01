"""Lint rules for the one-line skill description shown in every planner catalogue."""

from __future__ import annotations

from agent_fabric import build_registry
from agent_fabric.lint import lint_skills

TEMPLATE = """---
name: {name}
version: 1.0.0
domain: demo
description: {description}
runtime: prompt
inputs: {{ text: {{ type: text }} }}
outputs: {{ out: {{ type: text }} }}
---

# {name}
{when}
## Instructions

Summarise {{inputs.text}}.
"""
WHEN = "\n## When to use\n\nWhen a short recap of a document is needed.\n"


def codes(tmp_path, *skills: tuple[str, str, bool]) -> dict[str, set[str]]:
    for name, description, with_when in skills:
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(TEMPLATE.format(name=name, description=description, when=WHEN if with_when else ""))
    found: dict[str, set[str]] = {}
    for issue in lint_skills(build_registry([str(tmp_path)])):
        found.setdefault(issue.where.split("/")[-2], set()).add(issue.code)
    return found


def test_good_description_with_when_section_is_clean(tmp_path):
    out = codes(tmp_path, ("recap", "Condense a document into a short faithful recap.", True))
    assert not any(c.startswith("description_") for cs in out.values() for c in cs)


def test_trigger_in_description_is_enough_without_when_section(tmp_path):
    out = codes(tmp_path, ("recap", "Condense a document into a recap; use it for long reports.", False))
    assert "description_no_trigger" not in out.get("recap", set())


def test_missing_trigger_is_flagged(tmp_path):
    out = codes(tmp_path, ("recap", "Condense a document into a short faithful recap.", False))
    assert "description_no_trigger" in out["recap"]


def test_filler_person_and_short_are_flagged(tmp_path):
    out = codes(
        tmp_path,
        ("a", "This component condenses a document into a recap.", True),
        ("b", "Helps you condense a document into a short recap.", True),
        ("c", "Recap it.", True),
    )
    assert "description_filler" in out["a"]
    assert "description_first_person" in out["b"]
    assert "description_too_short" in out["c"]


def test_duplicate_descriptions_are_flagged(tmp_path):
    same = "Condense a document into a short faithful recap."
    out = codes(tmp_path, ("one", same, True), ("two", same.upper(), True))
    assert "description_duplicate" in out["two"]
    assert "description_duplicate" not in out.get("one", set())
