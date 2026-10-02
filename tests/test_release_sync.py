"""tools/release_sync.py: rebuild conflicting release-please branches on main, leave mergeable ones alone."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_sync", Path(__file__).resolve().parents[1] / "tools" / "release_sync.py"
)
release_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_sync)

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True, env={**ENV, "PATH": "/usr/bin:/bin"}
    ).stdout


def write_manifest(repo: Path, **versions: str) -> None:
    (repo / ".release-please-manifest.json").write_text(
        json.dumps({f"packages/{k}": v for k, v in versions.items()}, indent=2) + "\n"
    )


def commit(repo: Path, message: str) -> None:
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-q", "-m", message)


def release_branch(repo: Path, pkg: str, version: str) -> str:
    """What release-please pushes: main + the package changelog + its manifest entry bumped, as one commit."""
    branch = f"{release_sync.PREFIX}{pkg}"
    run(repo, "git", "checkout", "-q", "-b", branch, "main")
    (repo / "packages" / pkg).mkdir(parents=True, exist_ok=True)
    (repo / "packages" / pkg / "CHANGELOG.md").write_text(f"# {pkg}\n\n## {version}\n- change\n")
    manifest = json.loads((repo / ".release-please-manifest.json").read_text())
    manifest[f"packages/{pkg}"] = version
    (repo / ".release-please-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    commit(repo, f"chore(main): release {pkg} {version}")
    run(repo, "git", "push", "-q", "origin", branch)
    run(repo, "git", "checkout", "-q", "main")
    return branch


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    run(tmp_path, "git", "clone", "-q", str(remote), str(work))
    run(work, "git", "checkout", "-q", "-b", "main")
    write_manifest(work, a="0.1.0", b="0.1.0")
    commit(work, "base")
    run(work, "git", "push", "-q", "origin", "main")
    return work, remote


def sync(work: Path, *extra: str, monkeypatch) -> str:
    monkeypatch.chdir(work)
    monkeypatch.setenv("GH_TOKEN", "x")  # push uses a credential helper that is unused for a local path remote
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert release_sync.main([*extra]) == 0
    return buf.getvalue()


def test_conflicting_release_branch_is_rebuilt_on_main(repos, monkeypatch):
    work, _remote = repos
    a, b = release_branch(work, "a", "0.2.0"), release_branch(work, "b", "0.2.0")
    # release a is merged: main now has a's manifest bump and changelog; b's branch still has the old manifest -> conflict
    run(work, "git", "merge", "-q", "--squash", f"origin/{a}")
    commit(work, "release a 0.2.0")
    run(work, "git", "push", "-q", "origin", "main")
    assert release_sync.git("fetch", "-q", "origin", cwd=work) is not None
    monkeypatch.chdir(work)
    assert release_sync.conflicts("origin", b)

    out = sync(work, monkeypatch=monkeypatch)
    assert f"{b}: rebuilt and pushed" in out

    run(work, "git", "fetch", "-q", "origin")
    manifest = json.loads(run(work, "git", "show", f"origin/{b}:.release-please-manifest.json"))
    assert manifest == {"packages/a": "0.2.0", "packages/b": "0.2.0"}  # main's entry for a, b's own bump
    assert "## 0.2.0" in run(work, "git", "show", f"origin/{b}:packages/b/CHANGELOG.md")
    assert run(work, "git", "log", "-1", "--format=%s", f"origin/{b}").strip() == "chore(main): release b 0.2.0"
    assert (
        run(work, "git", "rev-list", "--count", f"origin/main..origin/{b}").strip() == "1"
    )  # one commit on top of main
    assert not release_sync.conflicts("origin", b)


def test_mergeable_branch_is_left_alone(repos, monkeypatch):
    work, _remote = repos
    b = release_branch(work, "b", "0.2.0")
    before = run(work, "git", "rev-parse", f"origin/{b}").strip()
    out = sync(work, monkeypatch=monkeypatch)
    assert f"{b}: mergeable, left alone" in out
    run(work, "git", "fetch", "-q", "origin")
    assert run(work, "git", "rev-parse", f"origin/{b}").strip() == before


def test_dry_run_changes_nothing(repos, monkeypatch):
    work, _remote = repos
    a, b = release_branch(work, "a", "0.2.0"), release_branch(work, "b", "0.2.0")
    run(work, "git", "merge", "-q", "--squash", f"origin/{a}")
    commit(work, "release a 0.2.0")
    run(work, "git", "push", "-q", "origin", "main")
    before = run(work, "git", "rev-parse", f"origin/{b}").strip()
    out = sync(work, "--dry-run", monkeypatch=monkeypatch)
    assert "would rebuild (dry run)" in out
    run(work, "git", "fetch", "-q", "origin")
    assert run(work, "git", "rev-parse", f"origin/{b}").strip() == before


def test_without_a_token_nothing_is_pushed(repos, monkeypatch, capsys):
    work, _remote = repos
    monkeypatch.chdir(work)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert release_sync.main([]) == 0
    assert "GH_TOKEN is not set" in capsys.readouterr().out


def test_stale_branch_already_merged_is_skipped(repos, monkeypatch):
    work, _remote = repos
    release_branch(work, "a", "0.2.0")
    b = release_branch(work, "b", "0.2.0")
    # both releases end up in main (b's content identical to its branch), but b's branch still conflicts on the manifest lines
    run(work, "git", "checkout", "-q", f"origin/{b}", "--", "packages/b/CHANGELOG.md")
    write_manifest(work, a="0.2.0", b="0.2.0")
    commit(work, "releases a and b")
    run(work, "git", "push", "-q", "origin", "main")
    monkeypatch.chdir(work)
    run(work, "git", "fetch", "-q", "origin")
    assert release_sync.conflicts("origin", b)
    out = sync(work, monkeypatch=monkeypatch)
    assert f"{b}: skipped, main already contains its changes" in out
