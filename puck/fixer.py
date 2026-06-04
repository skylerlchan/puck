"""The pipeline. Given a queued Job, it: reproduces + fixes (Claude Code) ->
runs tests -> self-reviews (and revises) -> opens a PR -> posts the Fix Card.
On Accept (or automatically, at high autonomy) it rebases, merges, and deploys.

Every path cleans up its worktree and, on any failure, escalates to a human
rather than going silent.
"""
from __future__ import annotations

import re

from . import blocks, github_ops as gh, recorder
from .claude_runner import run_claude, extract_json
from .config import Config
from .models import FixResult, Job, Status
from .notify import Notifier
from .review import review_diff
from .store import Store

FIX_PROMPT = """A teammate reported this problem in our chat:

\"{description}\"
{hint}

You are in an isolated checkout of our repository. Do the following:
1. Reproduce the problem and find the root cause.
2. Make the smallest correct change that fixes it.
3. Add or update an automated test that fails before your change and passes after.
4. Run the test suite ({test_cmd}) and confirm it passes.

Write the plain_* fields so a non-engineer understands them (no jargon, no file
names). Keep root_cause/approach technical.

End your reply with ONLY this ```json block and nothing after it:
```json
{{
  "status": "fixed",
  "plain_summary": "one friendly sentence describing the fix",
  "what_was_wrong": "plain explanation of the problem",
  "what_changed": "plain explanation of what you did",
  "root_cause": "technical root cause",
  "approach": "technical approach",
  "files_changed": ["path/one", "path/two"],
  "test_added": "test name or path, or null",
  "confidence": 0.0,
  "notes_for_human": ""
}}
```
If you cannot confidently fix it, set "status": "cannot_fix" and put what you
found and where you got stuck in "notes_for_human"."""

REVISE_PROMPT = """A reviewer flagged these must-fix issues with your change.
Fix each one, keep the tests green, then output the same ```json block again.

Issues:
{issues}"""

FEATURE_PROMPT = """A teammate asked for this feature:

\"{description}\"
{hint}

You are in an isolated checkout. Build a small, working PROTOTYPE of the feature
(it doesn't have to be production-perfect) so people can see and react to it.
Then summarize it for a non-engineer.

End with ONLY this ```json block:
```json
{{
  "status": "fixed",
  "plain_summary": "what the feature does, one sentence",
  "what_changed": "plain description of the prototype",
  "files_changed": ["..."],
  "confidence": 0.0
}}
```"""


def _slug(text: str, n: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:n] or "fix").strip("-")


# --------------------------------------------------------------------------- #
#  Main entry: run a queued job to a posted card (or escalation).             #
# --------------------------------------------------------------------------- #
def run_job(job: Job, cfg: Config, store: Store, notifier: Notifier) -> None:
    if job.kind == "feature":
        return _run_feature(job, cfg, store, notifier)
    return _run_bug(job, cfg, store, notifier)


def _run_bug(job: Job, cfg: Config, store: Store, notifier: Notifier) -> None:
    repo = cfg.repos[job.repo_key]
    base = repo.base_branch
    store.update(job.id, status=Status.INVESTIGATING.value)
    notifier.post(blocks.working(job, cfg.bot_name))
    branch = f"fix/{job.id}-{_slug(job.description)}"

    try:
        wt = gh.prepare_worktree(repo.path, base, branch)
        store.update(job.id, branch=branch, worktree=wt)

        # 1. fix
        hint = f"\nExtra guidance from the team: {job.hint}" if job.hint else ""
        text, _ = run_claude(
            FIX_PROMPT.format(description=job.description, hint=hint,
                              test_cmd=repo.test_command or "your test command"),
            cwd=wt, skip_permissions=cfg.claude_skip_permissions, model=cfg.claude_model)
        data = extract_json(text)
        result = FixResult.from_dict(data)

        # "is there a real fix?" = a diff vs base, not just a dirty tree
        if result.status != "fixed" or not gh.changed_files(wt, base):
            result.notes_for_human = result.notes_for_human or "No confident fix produced."
            return _escalate(job, cfg, store, notifier, result)

        # 2/3. tests + self-review loop — both re-evaluated against the FINAL tree
        store.update(job.id, status=Status.REVIEWING.value)
        tests_ok, tests_summary = gh.run_tests(repo.test_command, wt)
        review = review_diff(wt, f"origin/{base}", custom_command=repo.review_command,
                             skip_permissions=cfg.claude_skip_permissions, model=cfg.claude_model)
        for _ in range(max(1, cfg.review_max_rounds)):
            if review.get("approved") and tests_ok:
                break
            issues = review.get("must_fix") or (["tests are failing"] if not tests_ok else [])
            if not issues:
                break
            rev_text, _ = run_claude(
                REVISE_PROMPT.format(issues="\n".join(f"- {i}" for i in issues)),
                cwd=wt, skip_permissions=cfg.claude_skip_permissions, model=cfg.claude_model)
            more = extract_json(rev_text)
            if more:
                result = FixResult.from_dict({**data, **more})
            # re-check BOTH against the revised tree before trusting either
            tests_ok, tests_summary = gh.run_tests(repo.test_command, wt)
            review = review_diff(wt, f"origin/{base}", custom_command=repo.review_command,
                                 skip_permissions=cfg.claude_skip_permissions, model=cfg.claude_model)

        result.tests_passed = tests_ok
        result.tests_summary = tests_summary
        result.review_passed = bool(review.get("approved"))
        result.review_notes = review.get("summary", "")
        result.files_changed = result.files_changed or gh.changed_files(wt, base)

        if not (result.review_passed and result.tests_passed):
            result.notes_for_human = (result.notes_for_human or "") + \
                f"\nReview/tests didn't fully pass: {result.review_notes} | tests: {tests_summary}"
            return _escalate(job, cfg, store, notifier, result)

        # 4. optional before/after capture
        if repo.repro:
            base_wt = gh.prepare_base_worktree(repo.path, base)
            try:
                result.before_video, result.after_video = recorder.record_before_after(repo.repro, base_wt, wt)
            finally:
                gh.cleanup_worktree(repo.path, base_wt)

        # 5. open the PR
        if gh.has_changes(wt):
            gh.commit_all(wt, f"fix: {result.plain_summary or job.description[:60]}")
        gh.push(wt, branch)
        pr_url, pr_num = gh.create_pr(
            wt, result.plain_summary or f"Fix: {job.description[:60]}", _pr_body(job, result), base)

        eta = repo.deploy_eta_minutes
        store.update(job.id, pr_url=pr_url, pr_number=pr_num, eta_minutes=eta,
                     result=result.__dict__, status=Status.AWAITING_ACCEPT.value)
        job = store.get(job.id)

        # 6. post the card. autonomy decides whether a human must tap Accept.
        auto = cfg.autonomy in ("auto", "workflow")
        for v, title in ((result.before_video, "Before"), (result.after_video, "After")):
            if v:
                notifier.upload_video(v, title)
        notifier.post(blocks.fix_card(job, result, eta, cfg.bot_name, needs_accept=not auto))
        if auto:
            ship_job(job.id, cfg, store, notifier)
    except Exception as e:  # never leak a worktree or go silent on a crash
        _fail(job, cfg, store, notifier, f"I hit an unexpected error while fixing this: {e}")


def _run_feature(job: Job, cfg: Config, store: Store, notifier: Notifier) -> None:
    repo = cfg.repos[job.repo_key]
    store.update(job.id, status=Status.INVESTIGATING.value)
    notifier.post(blocks.working(job, cfg.bot_name))
    branch = f"feat/{job.id}-{_slug(job.description)}"
    try:
        wt = gh.prepare_worktree(repo.path, repo.base_branch, branch)
        store.update(job.id, branch=branch, worktree=wt)
        hint = f"\nExtra guidance: {job.hint}" if job.hint else ""
        text, _ = run_claude(FEATURE_PROMPT.format(description=job.description, hint=hint),
                            cwd=wt, skip_permissions=cfg.claude_skip_permissions, model=cfg.claude_model)
        result = FixResult.from_dict(extract_json(text))
        result.files_changed = result.files_changed or gh.changed_files(wt, repo.base_branch)
        store.update(job.id, result=result.__dict__, status=Status.AWAITING_ACCEPT.value)
        notifier.post(blocks.feature_card(store.get(job.id), result, cfg.bot_name))
    except Exception as e:
        _fail(job, cfg, store, notifier, f"I hit an error building the mockup: {e}")


# --------------------------------------------------------------------------- #
#  Accept / Reject actions                                                    #
# --------------------------------------------------------------------------- #
def ship_job(job_id: str, cfg: Config, store: Store, notifier: Notifier) -> None:
    # atomic claim: only one Accept can move AWAITING -> SHIPPING
    job = store.update_if(job_id, Status.AWAITING_ACCEPT.value, status=Status.SHIPPING.value)
    if not job:
        return  # already shipping/shipped/rejected, or unknown
    repo = cfg.repos[job.repo_key]
    eta = job.eta_minutes or repo.deploy_eta_minutes
    wt = job.worktree
    notifier.post(blocks.shipping(eta))
    try:
        if not wt:
            raise gh.GitError("no worktree to ship from")
        gh.rebase_on_base(wt, repo.base_branch)            # rebase with main…
        ok, summary = gh.run_tests(repo.test_command, wt)  # …re-validate on the new base
        if not ok:
            res = FixResult(**(job.result or {}))
            res.notes_for_human = f"Tests failed after rebasing on {repo.base_branch}: {summary}"
            gh.cleanup_worktree(repo.path, wt)
            store.update(job_id, worktree=None)
            return _escalate(store.get(job_id), cfg, store, notifier, res)
        gh.merge_pr(wt)                                    # …then merge
    except Exception as e:
        if wt:
            gh.cleanup_worktree(repo.path, wt)
        store.update(job_id, status=Status.FAILED.value, worktree=None)
        notifier.post(blocks.deploy_failed(f"Couldn't ship: {e}"))
        return

    # …then deploy from a FRESH checkout of the post-merge base, not the feature tree
    deploy_ok, deploy_out = True, ""
    if repo.deploy_command:
        base_wt = gh.prepare_base_worktree(repo.path, repo.base_branch)
        try:
            deploy_ok, deploy_out = gh.run_deploy(repo.deploy_command, base_wt)
        finally:
            gh.cleanup_worktree(repo.path, base_wt)
    gh.cleanup_worktree(repo.path, wt)

    if not deploy_ok:
        store.update(job_id, status=Status.FAILED.value, worktree=None)
        notifier.post(blocks.deploy_failed(deploy_out))
        return
    store.update(job_id, status=Status.LIVE.value, worktree=None)
    notifier.post(blocks.live(store.get(job_id)))


def reject_job(job_id: str, cfg: Config, store: Store, notifier: Notifier) -> None:
    job = store.update_if(job_id, Status.AWAITING_ACCEPT.value, status=Status.REJECTED.value)
    if not job:
        return  # already actioned
    if job.worktree:
        repo = cfg.repos[job.repo_key]
        gh.close_pr(job.worktree)
        gh.cleanup_worktree(repo.path, job.worktree)
        store.update(job_id, worktree=None)
    notifier.post(blocks.rejected())


def _fail(job: Job, cfg: Config, store: Store, notifier: Notifier, message: str) -> None:
    """A crash mid-pipeline: hand the human whatever the bot got to, cleanly."""
    res = FixResult(status="cannot_fix", notes_for_human=message)
    _escalate(store.get(job.id) or job, cfg, store, notifier, res)


def _escalate(job: Job, cfg: Config, store: Store, notifier: Notifier, result: FixResult) -> None:
    job = store.get(job.id) or job
    repo = cfg.repos[job.repo_key]
    pushed = False
    if job.worktree:
        try:
            if gh.has_changes(job.worktree):
                gh.commit_all(job.worktree, f"wip: draft fix for {job.id}")
            if job.branch and gh.changed_files(job.worktree, repo.base_branch):
                gh.push(job.worktree, job.branch)
                pushed = True
        except Exception:  # never let cleanup failure swallow the escalation
            pushed = False
        finally:
            gh.cleanup_worktree(repo.path, job.worktree)   # don't leak the worktree
            store.update(job.id, worktree=None)
    if not pushed:
        store.update(job.id, branch=None)  # don't promise a draft branch that isn't there
    engineer = store.next_engineer(cfg.team)
    job = store.update(job.id, status=Status.NEEDS_HUMAN.value, result=result.__dict__)
    notifier.post(blocks.escalation(job, result, engineer, cfg.team, cfg.bot_name))


def _pr_body(job: Job, result: FixResult) -> str:
    return (
        f"**Reported by:** {job.reporter}\n\n"
        f"**Problem:** {job.description}\n\n"
        f"**Root cause:** {result.root_cause}\n\n"
        f"**Fix:** {result.approach}\n\n"
        f"**Test:** {result.test_added or '—'}\n\n"
        f"_Opened by Puck · job {job.id}_"
    )
