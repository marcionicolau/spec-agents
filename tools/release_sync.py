"""Keep release-please PRs mergeable: rebuild a release PR branch on top of the current main when it conflicts.

release-please opens one release PR per package and every one of them edits the shared ``.release-please-manifest.json``. After one release
PR is merged, the others conflict on that file. This tool rebuilds each conflicting release branch as *main + the PR's own changes*
(changelog, version file) with only its own manifest entry bumped, keeps the PR's commit message, and force-pushes it (with lease). CI then
runs again on the PR, so the required checks stay meaningful. Nothing is touched when a branch merges cleanly.

    python tools/release_sync.py [--dry-run] [--repo OWNER/REPO] [--remote origin]

Used by the ``sync-release-prs`` job of ``.github/workflows/release.yml`` (token: ``RELEASE_PLEASE_TOKEN``, so the push triggers CI) and by
``just release-sync``. With ``--repo`` (and ``gh`` authenticated) only branches that have an open PR are considered.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MANIFEST = ".release-please-manifest.json"
PREFIX = "release-please--branches--main--components--"
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")


def git(*args: str, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def release_branches(remote: str, open_pr_heads: set[str] | None) -> list[str]:
    out = git("for-each-ref", "--format=%(refname:strip=3)", f"refs/remotes/{remote}/{PREFIX}*").stdout.split()
    return sorted(b for b in out if open_pr_heads is None or b in open_pr_heads)


def open_pr_heads(repo: str) -> set[str]:
    out = subprocess.run(
        ["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "headRefName"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {p["headRefName"] for p in json.loads(out)}


def conflicts(remote: str, branch: str) -> bool:
    """Whether merging the release branch into the remote main would conflict (computed locally, no API lag)."""
    return git("merge-tree", "--write-tree", f"{remote}/main", f"{remote}/{branch}", check=False).returncode != 0


def changed_files(remote: str, branch: str) -> list[str]:
    return git("diff", "--name-only", f"{remote}/main...{remote}/{branch}").stdout.split()


def rebuild(remote: str, branch: str, push: bool, token_env: str = "GH_TOKEN") -> str:
    """Rebuild ``branch`` on the remote main; returns a one-line description of what was done."""
    component = branch.removeprefix(PREFIX)
    key = f"packages/{component}"
    own = [f for f in changed_files(remote, branch) if f != MANIFEST]
    manifest_branch = json.loads(git("show", f"{remote}/{branch}:{MANIFEST}").stdout)
    if key not in manifest_branch:
        return f"{branch}: skipped, no '{key}' entry in its manifest"
    message = git("log", "-1", "--format=%B", f"{remote}/{branch}").stdout.strip()
    old_sha = git("rev-parse", f"{remote}/{branch}").stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        git("worktree", "add", "--detach", str(wt), f"{remote}/main")
        try:
            for f in own:
                (wt / f).parent.mkdir(parents=True, exist_ok=True)
                (wt / f).write_text(git("show", f"{remote}/{branch}:{f}").stdout, encoding="utf-8")
            manifest = json.loads((wt / MANIFEST).read_text(encoding="utf-8"))
            manifest[key] = manifest_branch[key]
            (wt / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            git("add", "-A", cwd=wt)
            if git("diff", "--cached", "--quiet", cwd=wt, check=False).returncode == 0:
                return f"{branch}: skipped, main already contains its changes (stale branch)"
            git("-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-q", "-m", message, cwd=wt)
            new_sha = git("rev-parse", "HEAD", cwd=wt).stdout.strip()
            if push:
                helper = f"!f() {{ echo username=x-access-token; echo password=${token_env}; }}; f"
                git(
                    "-c",
                    f"credential.helper={helper}",
                    "push",
                    f"--force-with-lease={branch}:{old_sha}",
                    remote,
                    f"{new_sha}:refs/heads/{branch}",
                    cwd=wt,
                )
        finally:
            git("worktree", "remove", "--force", str(wt), check=False)
    verb = "rebuilt and pushed" if push else "would rebuild (dry run)"
    return f"{branch}: {verb} on main ({manifest_branch[key]} for {key}; files: {', '.join(own) or 'none'})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--repo", help="OWNER/REPO: only consider branches with an open PR (needs gh)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, push nothing")
    a = ap.parse_args(argv)
    if not a.dry_run and not os.environ.get("GH_TOKEN"):
        print("GH_TOKEN is not set: nothing pushed (use --dry-run to only look)")
        return 0
    git("fetch", "--quiet", a.remote, f"+refs/heads/*:refs/remotes/{a.remote}/*")
    heads = open_pr_heads(a.repo) if a.repo else None
    branches = release_branches(a.remote, heads)
    if not branches:
        print("no release-please branches")
        return 0
    for b in branches:
        if conflicts(a.remote, b):
            print(rebuild(a.remote, b, push=not a.dry_run))
        else:
            print(f"{b}: mergeable, left alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
