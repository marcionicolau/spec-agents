"""Export of fabric skills as spec-compliant Agent Skills, and the validator that checks them."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_fabric import build_registry
from agent_fabric.cli import build_parser
from agent_fabric.cli.commands import cmd_export_skills
from agent_fabric.errors import SpecError
from agent_fabric.markdown import read_markdown
from agent_fabric.skills_export import (
    DESCRIPTION_MAX,
    export_description,
    export_name,
    export_registry,
    validate_skill_dir,
    validate_tree,
)

NOTES = Path(__file__).resolve().parents[3] / "examples" / "notes" / "skills"


@pytest.fixture
def registry():
    return build_registry([str(NOTES)])


def test_export_name_is_kebab_case():
    assert export_name("linear_model") == "linear-model"
    assert export_name("pca") == "pca"


def test_exported_skills_are_valid_and_keep_the_original_name(registry, tmp_path):
    written = export_registry(registry, tmp_path)
    assert len(written) == len(registry.names())
    assert validate_tree(tmp_path) == []
    skill = tmp_path / "summarize-notes" / "SKILL.md"
    doc = read_markdown(skill)
    assert set(doc.meta) == {"name", "description", "license", "compatibility", "metadata"}
    assert doc.meta["name"] == "summarize-notes"
    assert doc.meta["metadata"]["fabric-name"] == "summarize_notes"
    assert all(isinstance(v, str) for v in doc.meta["metadata"].values())
    assert "## Contract (agent-fabric)" in doc.body
    assert "param `tone`" in doc.body


def test_description_carries_what_and_when_within_the_limit(registry):
    spec = registry.get("summarize_notes").spec
    text = export_description(spec)
    assert text.startswith(spec.description.rstrip("."))
    assert "When to use:" in text
    assert len(text) <= DESCRIPTION_MAX


def test_validator_rejects_what_the_reference_validator_rejects(tmp_path):
    def make(dirname: str, front: str) -> Path:
        d = tmp_path / dirname
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\n{front}\n---\n\nbody\n")
        return d

    assert validate_skill_dir(make("good-skill", "name: good-skill\ndescription: Does a thing. Use when needed.")) == []
    assert any(
        "unexpected fields" in e for e in validate_skill_dir(make("a", "name: a\ndescription: x\nversion: 1.0.0"))
    )
    assert any(
        "must be lowercase" in e for e in validate_skill_dir(make("snake_case", "name: snake_case\ndescription: x"))
    )
    assert any("must match the directory" in e for e in validate_skill_dir(make("b", "name: other\ndescription: x")))
    assert any("description is required" in e for e in validate_skill_dir(make("c", "name: c\ndescription: ''")))
    long = "d" * (DESCRIPTION_MAX + 1)
    assert any("description longer" in e for e in validate_skill_dir(make("d", f"name: d\ndescription: {long}")))
    nested = "name: e\ndescription: x\nmetadata:\n  params:\n    k: 1"
    assert any("metadata must map" in e for e in validate_skill_dir(make("e", nested)))
    assert any("no SKILL.md" in e for e in validate_skill_dir(tmp_path / "missing"))


def test_name_collisions_are_reported(registry, tmp_path):
    spec = registry.get("summarize_notes").spec
    clone = spec.model_copy(update={"name": "summarize-notes"})  # only possible by hand: '_' and '-' export alike
    registry._components["summarize-notes"] = type("C", (), {"spec": clone})()
    with pytest.raises(SpecError) as ei:
        export_registry(registry, tmp_path)
    assert ei.value.details[0].type == "export_name_collision"


def test_cli_export_skills(tmp_path):
    from rich.console import Console

    args = build_parser().parse_args(["export-skills", "--out", str(tmp_path / "out"), "--skills", str(NOTES)])
    console = Console(file=__import__("io").StringIO(), width=200)
    assert cmd_export_skills(args, console) == 0
    assert "3 skill(s) exported" in console.file.getvalue()
    assert (tmp_path / "out" / "note-digest" / "SKILL.md").exists()
