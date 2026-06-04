"""Self-review pass — the '/code-review' step baked into the pipeline. Before a
fix is ever shown to a human, Claude reviews its own diff adversarially. If it
finds must-fix issues, the fixer feeds them back and tries again."""
from __future__ import annotations

import subprocess

from .claude_runner import run_claude, extract_json

REVIEW_PROMPT = """You are a strict senior reviewer. Review ONLY the changes in \
this checkout versus the base (use `git diff {diff_ref}`).

Check for: correctness bugs, missed edge cases, anything that could regress \
existing behavior, missing/weak test coverage for the change, and obvious \
security issues. Be adversarial — try to find a reason this should NOT ship.

Reply with a final ```json block and nothing after it:
{{
  "approved": true | false,
  "must_fix": ["specific, actionable issue", "..."],
  "summary": "one-sentence verdict"
}}
Set approved=false if there is ANY must_fix item."""


def review_diff(wt: str, diff_ref: str, *, custom_command: str | None = None,
                skip_permissions: bool = True, model: str | None = None) -> dict:
    """Review the diff vs `diff_ref` (e.g. 'origin/main' or a local commit SHA).
    Returns {approved: bool, must_fix: [...], summary: str}."""
    if custom_command:
        proc = subprocess.run(custom_command, cwd=wt, shell=True,
                              capture_output=True, text=True, timeout=900)
        ok = proc.returncode == 0
        return {"approved": ok, "must_fix": [] if ok else ["custom review failed"],
                "summary": "\n".join((proc.stdout or "").splitlines()[-4:])}

    text, _ = run_claude(REVIEW_PROMPT.format(diff_ref=diff_ref), cwd=wt,
                         skip_permissions=skip_permissions, model=model)
    data = extract_json(text)
    if not data:
        # if the reviewer didn't return structured output, fail closed
        return {"approved": False, "must_fix": ["review produced no verdict"],
                "summary": "review inconclusive"}
    data.setdefault("approved", False)
    data.setdefault("must_fix", [])
    data.setdefault("summary", "")
    return data
