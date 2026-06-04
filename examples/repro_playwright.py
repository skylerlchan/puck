#!/usr/bin/env python3
"""Example Tier-1 repro hook for Puck — the 'hidden screen' for web-app bugs.

Puck runs this TWICE: once in main's checkout (PUCK_LABEL=before, buggy code) and
once in the fix worktree (PUCK_LABEL=after, fixed code), then attaches both clips
to the Fix Card. The browser is HEADLESS — it renders the real app to an offscreen
surface, so nothing appears on your Mac.

Use it:
  1. pip install playwright && playwright install chromium
  2. copy this into your repo, e.g. tools/puck/repro.py
  3. config.yaml ->  repro: "python tools/puck/repro.py"
  4. edit the DRIVE section to reproduce your bug

Contract: write a non-empty video to $PUCK_RECORD_OUT and exit 0. Anything else
and Puck quietly falls back to a text before/after (never a faked clip).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time

from playwright.sync_api import sync_playwright

OUT = os.environ["PUCK_RECORD_OUT"]          # where the clip MUST land
LABEL = os.environ.get("PUCK_LABEL", "run")  # "before" or "after"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise TimeoutError(f"app never came up on :{port}")


def main() -> None:
    port = _free_port()

    # --- 1. boot THIS checkout's app (buggy for 'before', fixed for 'after') ---
    app = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(port)],   # <-- your dev server
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "PORT": str(port)},
    )
    try:
        _wait_for_port(port)

        # --- 2. drive the failing flow on the hidden headless browser ----------
        vid_dir = tempfile.mkdtemp(prefix="puck-vid-")
        with sync_playwright() as p:
            browser = p.chromium.launch()  # headless: this is the hidden screen
            ctx = browser.new_context(
                record_video_dir=vid_dir,
                record_video_size={"width": 1280, "height": 800})
            page = ctx.new_page()

            # ===== EDIT: reproduce the reported bug =====
            page.goto(f"http://localhost:{port}/login")
            page.get_by_role("button", name="Login").click()
            # AFTER (fixed) this succeeds; BEFORE (buggy) it harmlessly times out
            try:
                page.wait_for_url("**/dashboard", timeout=8000)
            except Exception:
                pass
            page.screenshot(path=OUT.replace(".mp4", ".png"))
            # ============================================

            video_path = page.video.path()
            ctx.close()      # flushes the .webm to disk
            browser.close()

        shutil.copyfile(video_path, OUT)   # hand Puck the clip at the exact path
        print(f"[{LABEL}] recorded -> {OUT}")
    finally:
        app.terminate()


if __name__ == "__main__":
    main()
