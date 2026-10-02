"""Verify built wheels ship their skill specs, LICENSE and py.typed.

uv build --all-packages --out-dir dist && python tools/check_wheels.py dist
    python tools/check_wheels.py dist --expect-version 0.1.0   # release builds: exact version, no .dev suffix
"""

from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_skills(dist_name: str) -> set[str]:
    """SKILL.md files under packages/<dist>/src/<module>/skills, as paths relative to the module."""
    out: set[str] = set()
    for skills in (ROOT / "packages" / dist_name / "src").glob("*/skills"):
        out |= {str(p.relative_to(skills.parent)) for p in skills.rglob("*.md")}
    return out


def package_dir(dist_name: str) -> str:
    """Directory under packages/ of the distribution ``dist_name`` (read from each package's pyproject.toml)."""
    for pyproject in (ROOT / "packages").glob("*/pyproject.toml"):
        name = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["name"]
        if name.replace("_", "-").lower() == dist_name:
            return pyproject.parent.name
    raise SystemExit(f"no package with distribution name {dist_name!r} under packages/")


def wheel_version(wheel: Path) -> str:
    """Version part of a wheel file name (``name-version-tags.whl``)."""
    return wheel.name.split("-")[1]


def main(dist_dir: str, expect_version: str | None = None) -> int:
    problems: list[str] = []
    wheels = sorted(Path(dist_dir).glob("*.whl"))
    if not wheels:
        problems.append(f"no wheels in {dist_dir}")
    for wheel in wheels:
        dist_name = wheel.name.split("-")[0].replace("_", "-").lower()
        with zipfile.ZipFile(wheel) as z:
            names = set(z.namelist())
        if not any(n.endswith("/licenses/LICENSE") for n in names):
            problems.append(f"{wheel.name}: LICENSE missing")
        if not any(n.endswith("/py.typed") for n in names):
            problems.append(f"{wheel.name}: py.typed missing")
        shipped = {n.split("/", 1)[1] for n in names if "/skills/" in n and n.endswith(".md")}
        for rel in sorted(source_skills(package_dir(dist_name)) - shipped):
            problems.append(f"{wheel.name}: {rel} missing from wheel")
        if expect_version is not None and wheel_version(wheel) != expect_version:
            problems.append(f"{wheel.name}: version {wheel_version(wheel)} != expected {expect_version}")
        print(f"{wheel.name}: {len(shipped)} skill files")
    for p in problems:
        print("ERROR", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    expect = args[args.index("--expect-version") + 1] if "--expect-version" in args else None
    positional = [
        a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--expect-version")
    ]
    sys.exit(main(positional[0] if positional else "dist", expect))
