"""Notifier abstraction so the fixer doesn't depend on Slack. The real bot passes
a SlackNotifier (in app.py); the CLI passes a ConsoleNotifier for local testing."""
from __future__ import annotations

import json


class Notifier:
    def post(self, blocks: list[dict], text: str = "") -> str:
        raise NotImplementedError

    def upload_video(self, path: str, title: str = "") -> None:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    """Prints what would be posted — used by the CLI to dry-run a fix."""

    def post(self, blocks: list[dict], text: str = "") -> str:
        print("\n--- slack message ---")
        for b in blocks:
            t = b.get("type")
            if t == "header":
                print(f"# {b['text']['text']}")
            elif t in ("section", "context"):
                if t == "section":
                    print(b["text"]["text"])
                else:
                    print("  " + " ".join(e.get("text", "") for e in b["elements"]))
            elif t == "actions":
                btns = " ".join(f"[{e['text']['text']}]" for e in b["elements"])
                print(f"buttons: {btns}")
        print("--- end ---")
        return "console-ts"

    def upload_video(self, path: str, title: str = "") -> None:
        print(f"[video] {title}: {path}")
