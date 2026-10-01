"""The Python snippets of docs/quickstart.md are executed, so the guide cannot drift from the code."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = ROOT / "docs" / "quickstart.md"


def python_blocks(path: Path) -> list[str]:
    return re.findall(r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.S)


def test_quickstart_has_runnable_examples():
    assert len(python_blocks(QUICKSTART)) >= 2


@pytest.mark.parametrize("index", range(len(python_blocks(QUICKSTART))))
def test_quickstart_snippet_runs(index, monkeypatch):
    monkeypatch.chdir(ROOT)  # snippets use repo-relative paths such as examples/notes
    monkeypatch.setattr(os, "environ", dict(os.environ))
    exec(compile(python_blocks(QUICKSTART)[index], f"{QUICKSTART.name}[{index}]", "exec"), {"__name__": "__docs__"})
