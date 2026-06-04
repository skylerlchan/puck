"""Before/after capture. Real video needs a per-repo reproduction hook (a script
that drives the failing scenario). If one is configured we run it on the base
checkout (before) and the fix worktree (after) and capture each. If not, we
degrade gracefully to None and the card shows a text before/after instead.

This keeps the promise honest: video when you give it a repro hook, words when
you don't — never a faked clip.
"""
from __future__ import annotations

import os
import subprocess
import tempfile


def _capture(repro_command: str, cwd: str, label: str) -> str | None:
    """Run the repro hook with PUCK_RECORD_OUT pointing at a file it should write
    the recording to (mp4/gif/png — your hook decides)."""
    out = os.path.join(tempfile.mkdtemp(prefix=f"puck-{label}-"), f"{label}.mp4")
    env = {**os.environ, "PUCK_RECORD_OUT": out, "PUCK_LABEL": label}
    try:
        proc = subprocess.run(repro_command, cwd=cwd, shell=True, env=env,
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    return None


def record_before_after(repro_command: str | None, base_checkout: str,
                        fix_worktree: str) -> tuple[str | None, str | None]:
    if not repro_command:
        return None, None
    before = _capture(repro_command, base_checkout, "before")
    after = _capture(repro_command, fix_worktree, "after")
    return before, after
