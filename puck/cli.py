"""Local testing without Slack.

  python -m puck.cli --mock                                  # render a sample card, no deps
  python -m puck.cli --local /path/to/repo "the bug" --test-cmd "pytest -q"   # real local fix, no GitHub
  python -m puck.cli "the X button is broken" --repo default # full pipeline (needs config + gh)
"""
from __future__ import annotations

import argparse

from . import blocks, fixer
from .config import Config
from .models import FixResult, Job
from .notify import ConsoleNotifier
from .store import Store


def _mock() -> None:
    job = Job.new("bug", "the login button does nothing on mobile", "default", "you")
    job.pr_url, job.pr_number = "https://github.com/acme/app/pull/123", 123
    result = FixResult(
        status="fixed",
        plain_summary="Login now works on phones",
        what_was_wrong="On phones, tapping Login did nothing — the tap wasn't reaching the button.",
        what_changed="Made sure the button receives taps, and added a test so it can't silently break again.",
        root_cause="An invisible overlay sat on top of the button and absorbed the tap.",
        approach="Lowered the overlay and disabled its pointer events when idle.",
        files_changed=["LoginForm.tsx", "overlay.css"],
        test_added="login.mobile.spec.ts", tests_passed=True, review_passed=True,
        confidence=0.9)
    n = ConsoleNotifier()
    n.post(blocks.queued(job, 1, "Puck"))
    n.post(blocks.fix_card(job, result, 8, "Puck", needs_accept=True))
    print("\n(escalation variant)")
    n.post(blocks.escalation(job, FixResult(notes_for_human="VAT looks double-applied but the fixtures don't cover it."),
                             None, [], "Puck"))


def _local(repo_path: str, description: str, test_cmd: str | None, base: str) -> None:
    from . import github_ops as gh
    from .local import local_fix
    print(f"Puck is fixing locally in {repo_path} …\n")
    out = local_fix(repo_path, description, base_ref=base, test_command=test_cmd)
    r = out.result
    print("=" * 60)
    print(f"status        : {r.status}")
    print(f"summary       : {r.plain_summary or '—'}")
    print(f"what was wrong: {r.what_was_wrong or '—'}")
    print(f"what changed  : {r.what_changed or '—'}")
    print(f"tests         : {'PASSED' if r.tests_passed else 'FAILED'} ({r.tests_summary.strip()[:60]})")
    print(f"self-review   : {'approved' if r.review_passed else 'not approved'}")
    print(f"files         : {', '.join(r.files_changed) or '—'}")
    print("=" * 60)
    print("\n--- diff ---")
    print(out.diff or "(no changes)")
    # clean the temp worktree but keep the branch so you can use the fix
    gh.cleanup_worktree(repo_path, out.worktree)
    print(f"\nApplied on branch `{out.branch}` — `git -C {repo_path} checkout {out.branch}` to use it.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Puck CLI")
    ap.add_argument("description", nargs="?", help="the bug/feature to work on")
    ap.add_argument("--repo", default=None, help="repo key from config.yaml")
    ap.add_argument("--local", metavar="REPO_PATH", default=None,
                    help="fix a bug in this local repo with NO GitHub/Slack")
    ap.add_argument("--test-cmd", default=None, help="test command for local mode, e.g. 'pytest -q'")
    ap.add_argument("--base", default="HEAD", help="base ref for local mode (default HEAD)")
    ap.add_argument("--feature", action="store_true", help="treat as a feature request")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--mock", action="store_true", help="render a sample card and exit")
    args = ap.parse_args()

    if args.mock:
        return _mock()
    if args.local:
        if not args.description:
            ap.error("--local needs a bug description")
        return _local(args.local, args.description, args.test_cmd, args.base)
    if not args.description:
        return _mock()

    cfg = Config.load(args.config)
    store = Store(f"{cfg.data_dir}/state.json")
    repo_key = args.repo or cfg.default_repo_key()
    job = Job.new("feature" if args.feature else "bug", args.description, repo_key, "cli-user")
    store.put(job)
    fixer.run_job(job, cfg, store, ConsoleNotifier())


if __name__ == "__main__":
    main()
