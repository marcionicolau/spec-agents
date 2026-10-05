"""The scripts under ``examples/docs`` are embedded in the documentation site: they must run offline and succeed."""

import runpy
from pathlib import Path

import pytest

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples" / "docs").glob("*.py"))


def test_examples_exist():
    assert EXAMPLES, "examples/docs has no scripts"


@pytest.mark.parametrize("script", EXAMPLES, ids=lambda p: p.stem)
def test_example_runs(script, capsys, monkeypatch):
    monkeypatch.delenv("COWORKER_ALLOWED_ROOTS", raising=False)
    runpy.run_path(str(script), run_name="__main__")
    assert capsys.readouterr().out.strip()
