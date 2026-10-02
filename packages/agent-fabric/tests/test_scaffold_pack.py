"""`scaffold pack` generates a complete domain pack: layout, repo wiring, ruff-clean code."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from agent_fabric.scaffold import scaffold_pack


def load_generated(pack: Path, module: str):
    """Exec the generated ``src/<module>/__init__.py`` as a module (no install needed)."""
    spec = importlib.util.spec_from_file_location(module, pack / "src" / module / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pack_layout_and_names(tmp_path):
    pack = scaffold_pack("geo-pack", tmp_path / "packages")
    assert pack == tmp_path / "packages" / "geo-pack"
    for rel in (
        "pyproject.toml",
        "README.md",
        "src/geo_pack/__init__.py",
        "src/geo_pack/py.typed",
        "src/geo_pack/skills/echo/SKILL.md",
        "tests/test_geo_pack.py",
    ):
        assert (pack / rel).exists(), rel
    pyproject = tomllib.loads((pack / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == "spec-agents-geo"  # -pack suffix dropped
    assert pyproject["project"]["entry-points"]["agent_fabric.domains"] == {"geo": "geo_pack:register"}
    assert pyproject["tool"]["uv-dynamic-versioning"]["pattern-prefix"] == "geo-pack-"


def test_generated_module_registers_and_runs(tmp_path):
    from agent_fabric import build_registry
    from agent_fabric.testing import run_component

    mod = load_generated(scaffold_pack("geo-pack", tmp_path / "packages"), "geo_pack")
    reg = build_registry([mod.register])
    assert reg.names(["geo"]) == ["echo"]
    res, _ = run_component(reg, "echo", {"uppercase": True}, text="hello")
    assert res.text == "HELLO" and res.n_chars == 5


def test_generated_python_is_ruff_clean(tmp_path):
    ruff = shutil.which("ruff")
    if not ruff:
        pytest.skip("ruff not on PATH")
    # repo-shaped root so the wiring adds geo_pack to known-first-party, matching real use
    (tmp_path / "packages").mkdir()
    (tmp_path / "release-please-config.json").write_text(json.dumps({"packages": {}}))
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nline-length = 120\ntarget-version = "py312"\n\n[tool.ruff.lint]\n'
        'select = ["F", "UP", "E", "I", "B", "SIM", "RUF", "PT"]\n'
        'ignore = ["E501", "PT018", "RUF005", "RUF012", "B905"]\n\n'
        '[tool.ruff.lint.isort]\nknown-first-party = ["agent_fabric"]\n'
    )
    pack = scaffold_pack("geo-pack", tmp_path / "packages")
    assert '"geo_pack"' in (tmp_path / "pyproject.toml").read_text()
    for target in (pack / "src", pack / "tests"):
        for args in (["check", "--config", str(tmp_path / "pyproject.toml")], ["format", "--check"]):
            proc = subprocess.run([ruff, *args, str(target)], capture_output=True, text=True)
            assert proc.returncode == 0, proc.stdout + proc.stderr


def test_name_and_module_validation(tmp_path):
    with pytest.raises(ValueError):
        scaffold_pack("Geo_Pack", tmp_path)
    scaffold_pack("geo-pack", tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_pack("geo-pack", tmp_path)


def test_stdlib_collision_gets_pack_suffix(tmp_path):
    pack = scaffold_pack("email", tmp_path / "packages")
    assert (pack / "src/email_pack/__init__.py").exists()
    pyproject = tomllib.loads((pack / "pyproject.toml").read_text())
    assert pyproject["project"]["entry-points"]["agent_fabric.domains"] == {"email": "email_pack:register"}


def test_repo_wiring(tmp_path):
    """With a repo-shaped root the shared files get their entries (release-please, labels, isort)."""
    root = tmp_path
    (root / "packages").mkdir()
    (root / ".github").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "LICENSE").write_text("MIT\n")
    (root / "release-please-config.json").write_text(json.dumps({"packages": {}}))
    (root / ".release-please-manifest.json").write_text(json.dumps({}))
    (root / ".github/labeler.yml").write_text('"pkg:specs":\n  - changed-files: []\n')
    (root / ".github/labels.yml").write_text('- name: "pkg:specs"\n  color: "5319e7"\n')
    (root / "pyproject.toml").write_text('known-first-party = ["agent_fabric"]\n')
    (root / "tests/test_public_api.py").write_text('PACKAGES = ["agent_fabric"]\n')
    (root / "justfile").write_text('packages := "agent-fabric"\nspecs:\n    uv run agent-fabric catalog\n')
    (root / "docs/packs.md").write_text("table\n\n- **statistics**: x\n- **notes**: y\nPer-package API: z\n")
    (root / "docs/gen_reference.py").write_text(
        'PYPI_NAMES = {\n    "text-pack": "spec-agents-text",\n}\nPACKAGES = {\n'
        '    "text-pack": ("text_pack", "Text."),\n}\n'
    )
    notes: list[str] = []
    scaffold_pack("geo-pack", root / "packages", notes=notes)
    assert notes == []
    cfg = json.loads((root / "release-please-config.json").read_text())
    assert cfg["packages"]["packages/geo-pack"]["component"] == "geo-pack"
    assert json.loads((root / ".release-please-manifest.json").read_text()) == {"packages/geo-pack": "0.0.1"}
    assert "pkg:geo-pack" in (root / ".github/labeler.yml").read_text()
    assert '"geo_pack"' in (root / "pyproject.toml").read_text()
    assert '"geo_pack"' in (root / "tests/test_public_api.py").read_text()
    just = (root / "justfile").read_text()
    assert "geo-pack" in just and "geo_pack:register" in just
    assert "| `geo-pack` | `geo_pack` |" in (root / "docs/packs.md").read_text()
    assert '"geo-pack": "spec-agents-geo"' in (root / "docs/gen_reference.py").read_text()


def test_standalone_outside_repo_collects_notes(tmp_path):
    notes: list[str] = []
    scaffold_pack("geo-pack", tmp_path / "modules", notes=notes)  # no repo root -> wiring skipped, noted
    assert any("release-please" in n for n in notes)


def test_main_pack(tmp_path, capsys):
    from agent_fabric.scaffold import main

    main(["pack", "geo-pack", "--dir", str(tmp_path / "packages")])
    assert (tmp_path / "packages/geo-pack/src/geo_pack").is_dir()
    assert "just check" in capsys.readouterr().out
