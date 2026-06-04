"""Git + GitHub plumbing via the `git` and `gh` CLIs (no tokens to wrangle —
reuse the gh auth already on the worker). Each job gets an isolated worktree so
fixes never touch the real working copy and many can run in parallel."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: str | None = None, timeout: int = 600) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise GitError(f"{' '.join(args)}\n{proc.stdout}\n{proc.stderr}")
    return (proc.stdout or "").strip()


def prepare_worktree(repo_path: str, base_branch: str, branch: str) -> str:
    """Create a fresh worktree off the latest base branch and return its path."""
    _run(["git", "-C", repo_path, "fetch", "origin", base_branch])
    wt = tempfile.mkdtemp(prefix="puck-")
    _run(["git", "-C", repo_path, "worktree", "add", "-b", branch, wt,
          f"origin/{base_branch}"])
    return wt


def prepare_worktree_local(repo_path: str, base_ref: str, branch: str) -> str:
    """Like prepare_worktree but off a LOCAL ref (no remote/fetch) — used by local
    mode so Puck can fix a bug on your machine with no GitHub at all."""
    wt = tempfile.mkdtemp(prefix="puck-")
    _run(["git", "-C", repo_path, "worktree", "add", "-b", branch, wt, base_ref])
    return wt


def rev_parse(wt: str, ref: str = "HEAD") -> str:
    return _run(["git", "-C", wt, "rev-parse", ref])


def diff_against(wt: str, ref: str) -> str:
    return _run(["git", "-C", wt, "diff", ref])


def changed_files_ref(wt: str, ref: str) -> list[str]:
    out = _run(["git", "-C", wt, "diff", "--name-only", ref])
    return [l for l in out.splitlines() if l.strip()]


def prepare_base_worktree(repo_path: str, base_branch: str) -> str:
    """A throwaway detached checkout of the base branch — used to record the
    'before' (buggy) state without touching the live working copy."""
    _run(["git", "-C", repo_path, "fetch", "origin", base_branch])
    wt = tempfile.mkdtemp(prefix="puck-base-")
    _run(["git", "-C", repo_path, "worktree", "add", "--detach", wt,
          f"origin/{base_branch}"])
    return wt


def has_changes(wt: str) -> bool:
    return bool(_run(["git", "-C", wt, "status", "--porcelain"]))


def diff_stat(wt: str, base_branch: str) -> str:
    return _run(["git", "-C", wt, "diff", "--stat", f"origin/{base_branch}"])


def changed_files(wt: str, base_branch: str) -> list[str]:
    out = _run(["git", "-C", wt, "diff", "--name-only", f"origin/{base_branch}"])
    return [l for l in out.splitlines() if l.strip()]


def commit_all(wt: str, message: str) -> None:
    _run(["git", "-C", wt, "add", "-A"])
    _run(["git", "-C", wt, "commit", "-m", message])


def push(wt: str, branch: str) -> None:
    _run(["git", "-C", wt, "push", "-u", "origin", branch])


def create_pr(wt: str, title: str, body: str, base_branch: str) -> tuple[str, int]:
    url = _run(["gh", "pr", "create", "--title", title, "--body", body,
                "--base", base_branch], cwd=wt)
    num = int(_run(["gh", "pr", "view", "--json", "number", "-q", ".number"], cwd=wt))
    return url, num


def rebase_on_base(wt: str, base_branch: str) -> None:
    """The 'rebase with main then merge' the user never has to think about."""
    _run(["git", "-C", wt, "fetch", "origin", base_branch])
    _run(["git", "-C", wt, "rebase", f"origin/{base_branch}"])
    _run(["git", "-C", wt, "push", "--force-with-lease"])


def merge_pr(wt: str, method: str = "squash") -> None:
    _run(["gh", "pr", "merge", f"--{method}", "--delete-branch"], cwd=wt)


def close_pr(wt: str) -> None:
    try:
        _run(["gh", "pr", "close", "--delete-branch"], cwd=wt)
    except GitError:
        pass


def cleanup_worktree(repo_path: str, wt: str) -> None:
    try:
        _run(["git", "-C", repo_path, "worktree", "remove", wt, "--force"])
    except GitError:
        Path(wt).exists() and subprocess.run(["rm", "-rf", wt])


def _run_cmd(command: str, wt: str, timeout: int) -> tuple[bool, str]:
    """Run a shell command in `wt`; never raises. Returns (ok, tail-of-output)
    with stdout+stderr merged so the real failure (usually on stderr) shows up."""
    try:
        proc = subprocess.run(command, cwd=wt, shell=True,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.splitlines()[-8:])
    return proc.returncode == 0, tail or "(no output)"


def run_tests(test_command: str | None, wt: str, timeout: int = 1200) -> tuple[bool, str]:
    """Returns (passed, short_summary). No command configured => treated as a
    soft pass but flagged, so the card can lower confidence."""
    if not test_command:
        return True, "no test command configured"
    return _run_cmd(test_command, wt, timeout)


def run_deploy(deploy_command: str | None, wt: str, timeout: int = 1800) -> tuple[bool, str]:
    if not deploy_command:
        return True, "merge-only (no deploy step)"
    return _run_cmd(deploy_command, wt, timeout)
