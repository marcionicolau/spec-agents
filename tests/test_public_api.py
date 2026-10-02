"""The public API surface: what each module exports in ``__all__`` must exist and (ratchet) be documented.

Docstring debt (module-level classes/functions and the public methods of exported classes) is tracked in
``tests/public_api_undocumented.txt``: it may only shrink. Documenting a name means
removing it from the file (the test fails on stale entries); adding a new public name without a docstring fails.
Refresh the file after writing docstrings with ``python tests/test_public_api.py --update``.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

import pytest

PACKAGES = ["agent_fabric", "stat_fabric", "lake_fabric", "coworker_fabric", "text_pack"]
DEBT_FILE = Path(__file__).with_name("public_api_undocumented.txt")


def modules() -> list[str]:
    names = []
    for pkg in PACKAGES:
        root = importlib.import_module(pkg)
        names.append(pkg)
        names += [m.name for m in pkgutil.walk_packages(root.__path__, pkg + ".") if not m.name.endswith("__main__")]
    return names


def exported() -> dict[str, list[str]]:
    out = {}
    for name in modules():
        try:
            mod = importlib.import_module(name)
        except ImportError:  # optional framework missing (e.g. integrations without the extra)
            continue
        if hasattr(mod, "__all__"):
            out[name] = list(mod.__all__)
    return out


def undocumented() -> set[str]:
    missing = set()
    for name, names in exported().items():
        mod = importlib.import_module(name)
        for n in names:
            obj = getattr(mod, n)
            if (inspect.isclass(obj) or inspect.isfunction(obj)) and obj.__module__ == name and not inspect.getdoc(obj):
                missing.add(f"{name}.{n}")
    return missing


def undocumented_methods() -> set[str]:
    """Public methods defined by an exported class itself (not inherited, not dunder) that have no docstring."""
    missing = set()
    for name, names in exported().items():
        mod = importlib.import_module(name)
        for n in names:
            cls = getattr(mod, n)
            if not (inspect.isclass(cls) and cls.__module__ == name):
                continue
            for attr, member in vars(cls).items():
                fn = member.fget if isinstance(member, property) else getattr(member, "__func__", member)
                if attr.startswith("_") or not inspect.isfunction(fn):
                    continue
                if not inspect.getdoc(fn):
                    missing.add(f"{name}.{n}.{attr}")
    return missing


def debt() -> set[str]:
    return {line.strip() for line in DEBT_FILE.read_text().splitlines() if line.strip() and not line.startswith("#")}


def test_every_package_declares_its_public_api():
    assert set(PACKAGES) <= set(exported()), "each package __init__ must define __all__"


@pytest.mark.parametrize("module", sorted(exported()))
def test_all_names_resolve_and_are_unique(module):
    mod = importlib.import_module(module)
    names = list(mod.__all__)
    assert len(names) == len(set(names)), f"duplicates in {module}.__all__"
    assert [n for n in names if not hasattr(mod, n)] == [], f"{module}.__all__ lists names that do not exist"


def test_version_comes_from_the_installed_distribution():
    from importlib import metadata

    import agent_fabric

    assert agent_fabric.__version__ == metadata.version("spec-agents-core")


def test_docstring_debt_only_shrinks():
    missing, allowed = undocumented() | undocumented_methods(), debt()
    new = sorted(missing - allowed)
    stale = sorted(allowed - missing)
    assert not new, f"public names without a docstring (write one): {new}"
    assert not stale, (
        f"documented now, remove from {DEBT_FILE.name} (python tests/test_public_api.py --update): {stale}"
    )


if __name__ == "__main__":
    if "--update" in sys.argv:
        header = (
            "# Public names (in __all__) and public methods still without a docstring.\n"
            "# May only shrink; see tests/test_public_api.py.\n"
        )
        debt_now = undocumented() | undocumented_methods()
        DEBT_FILE.write_text(header + "".join(f"{n}\n" for n in sorted(debt_now)))
        print(f"{len(debt_now)} undocumented public names/methods written to {DEBT_FILE.name}")
