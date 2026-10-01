"""Verify built wheels ship their skill specs, LICENSE and py.typed.

uv build --all-packages --out-dir dist && python tools/check_wheels.py dist
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_skills(dist_name: str) -> set[str]:
    """SKILL.md files under packages/<dist>/src/<module>/skills, as paths relative to the module."""
    out: set[str] = set()
    for skills in (ROOT / "packages" / dist_name / "src").glob("*/skills"):
        out |= {str(p.relative_to(skills.parent)) for p in skills.rglob("*.md")}
    return out


def main(dist_dir: str) -> int:
    problems: list[str] = []
    wheels = sorted(Path(dist_dir).glob("*.whl"))
    if not wheels:
        problems.append(f"no wheels in {dist_dir}")
    for wheel in wheels:
        dist_name = wheel.name.split("-")[0].replace("_", "-")
        with zipfile.ZipFile(wheel) as z:
            names = set(z.namelist())
        if not any(n.endswith("/licenses/LICENSE") for n in names):
            problems.append(f"{wheel.name}: LICENSE missing")
        if not any(n.endswith("/py.typed") for n in names):
            problems.append(f"{wheel.name}: py.typed missing")
        shipped = {n.split("/", 1)[1] for n in names if "/skills/" in n and n.endswith(".md")}
        for rel in sorted(source_skills(dist_name) - shipped):
            problems.append(f"{wheel.name}: {rel} missing from wheel")
        print(f"{wheel.name}: {len(shipped)} skill files")
    for p in problems:
        print("ERROR", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist"))
