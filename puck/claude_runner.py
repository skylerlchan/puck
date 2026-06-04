"""Thin wrapper around the Claude Code CLI. This is what does the real work:
reproduce, fix, write tests, and (separately) review."""
from __future__ import annotations

import json
import re
import shutil
import subprocess


def claude_available() -> bool:
    return shutil.which("claude") is not None


def run_claude(prompt: str, cwd: str, *, timeout: int = 1800,
               skip_permissions: bool = True, model: str | None = None) -> tuple[str, int]:
    """Run Claude Code headless in `cwd`. Returns (final_text, returncode).

    `--dangerously-skip-permissions` is required for unattended edits; it is safe
    here ONLY because every job runs in a throwaway git worktree, never your real
    working copy.
    """
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ("", 124)
    # Fail CLOSED: a non-zero exit means the run errored — return empty text so
    # downstream (extract_json -> {}) treats it as "no fix"/"not approved" rather
    # than silently continuing on a partial result.
    if proc.returncode != 0:
        return ("", proc.returncode)
    out = (proc.stdout or "").strip()
    text = _final_text(out)
    return (text, 0)


def _final_text(out: str) -> str:
    """Claude Code's `--output-format json` may return a single result object OR a
    JSON array of stream events whose last 'result' element holds the final text.
    Handle both; fall back to the raw output. Returns '' if the run is_error."""
    try:
        obj = json.loads(out)
    except json.JSONDecodeError:
        return out
    if isinstance(obj, dict):
        return "" if obj.get("is_error") else obj.get("result", out)
    if isinstance(obj, list):
        for item in reversed(obj):
            if isinstance(item, dict) and (item.get("type") == "result" or "result" in item):
                return "" if item.get("is_error") else (item.get("result") or out)
    return out


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull the structured verdict out of Claude's reply. Tries a ```json fenced
    block first, then the last bare {...} object."""
    m = list(_JSON_BLOCK.finditer(text or ""))
    candidates = [mm.group(1) for mm in m]
    if not candidates:
        # last-resort: greedy bare object
        start = text.rfind("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidates = [text[start:end + 1]]
    for c in reversed(candidates):
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return {}
