"""Local mode — fix a bug on your machine with NO GitHub, NO Slack.

Puck makes an isolated worktree off your current branch, lets Claude Code fix the
bug, runs your tests, reviews its own diff, and hands you back the diff + the
branch. You decide whether to merge it. This is the 'does it work right now?'
path: all it needs is `claude` on PATH and a local git repo.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from . import github_ops as gh
from .claude_runner import run_claude, extract_json
from .fixer import FIX_PROMPT, _slug
from .models import FixResult
from .review import review_diff


@dataclass
class LocalOutcome:
    result: FixResult
    diff: str
    worktree: str
    branch: str
    base_sha: str


def local_fix(repo_path: str, description: str, *, base_ref: str = "HEAD",
              test_command: str | None = None, review: bool = True,
              skip_permissions: bool = True, model: str | None = None) -> LocalOutcome:
    branch = f"fix/local-{_slug(description)}-{uuid.uuid4().hex[:6]}"
    wt = gh.prepare_worktree_local(repo_path, base_ref, branch)
    base_sha = gh.rev_parse(wt, "HEAD")           # pin the pre-fix state

    text, _ = run_claude(
        FIX_PROMPT.format(description=description, hint="",
                          test_cmd=test_command or "your test command"),
        cwd=wt, skip_permissions=skip_permissions, model=model)
    result = FixResult.from_dict(extract_json(text))

    tests_ok, tests_summary = gh.run_tests(test_command, wt)
    result.tests_passed = tests_ok
    result.tests_summary = tests_summary

    if review and gh.changed_files_ref(wt, base_sha):
        verdict = review_diff(wt, base_sha, skip_permissions=skip_permissions, model=model)
        result.review_passed = bool(verdict.get("approved"))
        result.review_notes = verdict.get("summary", "")

    result.files_changed = result.files_changed or gh.changed_files_ref(wt, base_sha)
    diff = gh.diff_against(wt, base_sha)
    return LocalOutcome(result=result, diff=diff, worktree=wt, branch=branch, base_sha=base_sha)
