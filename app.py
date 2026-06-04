"""Puck — Slack entrypoint (Socket Mode, no public URL needed).

Run on an always-on worker:  python app.py
"""
from __future__ import annotations

import json
import re
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from puck import blocks, fixer
from puck.config import Config
from puck.models import Job, Status
from puck.notify import Notifier
from puck.queue import JobQueue
from puck.store import Store

cfg = Config.load("config.yaml")
store = Store(f"{cfg.data_dir}/state.json")
app = App(token=cfg.slack_bot_token)

_FEATURE_RE = re.compile(r"\b(feature|idea|can we (add|get|have)|i wish|it'd be nice)\b", re.I)


class SlackNotifier(Notifier):
    """Posts every message into the report's thread."""

    def __init__(self, channel: str, thread_ts: str):
        self.channel = channel
        self.thread_ts = thread_ts

    def post(self, blocks_: list[dict], text: str = "") -> str:
        resp = app.client.chat_postMessage(
            channel=self.channel, thread_ts=self.thread_ts,
            blocks=blocks_, text=text or "Puck update")
        return resp["ts"]

    def upload_video(self, path: str, title: str = "") -> None:
        try:
            app.client.files_upload_v2(channel=self.channel, thread_ts=self.thread_ts,
                                       file=path, title=title)
        except Exception as e:  # never let an upload hiccup kill the job
            print(f"[video upload failed] {e}")


def _worker(job: Job) -> None:
    fixer.run_job(job, cfg, store, SlackNotifier(job.channel, job.thread_ts))


jobq = JobQueue(_worker, concurrency=cfg.concurrency)


# --------------------------------------------------------------------------- #
#  Intake: mention the bot to report something                                #
# --------------------------------------------------------------------------- #
@app.event("app_mention")
def on_mention(event, say):
    text = re.sub(r"<@[^>]+>", "", event.get("text", "")).strip()
    if not text:
        return
    kind = "feature" if _FEATURE_RE.search(text) else "bug"
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    user = f"<@{event['user']}>"
    job = Job.new(kind, text, cfg.default_repo_key(), user, channel, thread_ts)
    store.put(job)
    pos = jobq.submit(job)
    say(blocks=blocks.queued(job, pos, cfg.bot_name), thread_ts=thread_ts,
        text="Queued")


# also accept plain messages in the dedicated channels (optional; needs the bot
# invited + message.channels scope). Mentions above are the reliable path.
@app.event("message")
def on_message(event, logger):
    # ignore bot messages, edits, and thread noise — only top-level human posts
    if event.get("bot_id") or event.get("subtype") or event.get("thread_ts"):
        return
    # (left as a no-op by default; enable channel routing here if you want
    #  mention-free intake. Resolve channel id -> name via conversations.info.)
    return


# --------------------------------------------------------------------------- #
#  Buttons                                                                     #
# --------------------------------------------------------------------------- #
def _run_bg(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


def _err(channel: str, thread_ts: str, e) -> None:
    """Surface a failed button press instead of letting Bolt swallow it silently."""
    try:
        app.client.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text=f":warning: That didn't go through ({e}). An engineer can check the logs.")
    except Exception:
        pass


@app.action("accept")
def on_accept(ack, body):
    ack()
    job = store.get(body["actions"][0]["value"])
    if not job:
        return
    # ship_job claims the job atomically (update_if), so a double-tap is a no-op
    _run_bg(fixer.ship_job, job.id, cfg, store, SlackNotifier(job.channel, job.thread_ts))


@app.action("reject")
def on_reject(ack, body):
    ack()
    job = store.get(body["actions"][0]["value"])
    if not job:
        return
    _run_bg(fixer.reject_job, job.id, cfg, store, SlackNotifier(job.channel, job.thread_ts))


@app.action("to_human")
def on_to_human(ack, body):
    ack()
    job_id = body["actions"][0]["value"]
    # claim atomically so a concurrent Accept can't also fire
    job = store.update_if(job_id, Status.AWAITING_ACCEPT.value, status=Status.NEEDS_HUMAN.value)
    if not job:
        return
    from puck.models import FixResult
    res = FixResult(**(job.result or {})) if job.result else FixResult()
    res.notes_for_human = res.notes_for_human or "A teammate asked for a human to look."
    _run_bg(fixer._escalate, job, cfg, store, SlackNotifier(job.channel, job.thread_ts), res)


@app.action("take_it")
def on_take_it(ack, body):
    ack()
    job_id = body["actions"][0]["value"]
    clicker = f"<@{body['user']['id']}>"
    # only the first clicker wins
    job = store.update_if(job_id, Status.NEEDS_HUMAN.value, status="owned")
    if not job:
        return
    try:
        app.client.chat_postMessage(channel=job.channel, thread_ts=job.thread_ts,
                                    text=f"{clicker} has got this one. :muscle:")
    except Exception as e:
        _err(job.channel, job.thread_ts, e)


@app.action("try_again")
@app.action("make_better")
@app.action("build_real")
def on_revise(ack, body, action):
    ack()
    job_id = action["value"]
    try:
        app.client.views_open(trigger_id=body["trigger_id"], view={
            "type": "modal", "callback_id": "revise_submit",
            "private_metadata": json.dumps({"action": action["action_id"], "job_id": job_id}),
            "title": {"type": "plain_text", "text": "What should change?"},
            "submit": {"type": "plain_text", "text": "Send"},
            "blocks": [{"type": "input", "block_id": "g", "optional": True,
                        "element": {"type": "plain_text_input", "multiline": True, "action_id": "v"},
                        "label": {"type": "plain_text", "text": "Guidance (optional)"}}],
        })
    except Exception as e:
        job = store.get(job_id)
        if job:
            _err(job.channel, job.thread_ts, e)


@app.view("revise_submit")
def on_revise_submit(ack, body, view):
    ack()
    try:
        meta = json.loads(view["private_metadata"])
        guidance = view["state"]["values"]["g"]["v"].get("value") or ""
        old = store.get(meta["job_id"])
        if not old:
            return
        kind = "bug" if meta["action"] == "build_real" else old.kind
        desc = old.description if meta["action"] != "build_real" else f"Implement feature: {old.description}"
        job = Job.new(kind, desc, old.repo_key, old.reporter, old.channel, old.thread_ts)
        job.hint = guidance
        store.put(job)
        pos = jobq.submit(job)
        app.client.chat_postMessage(channel=job.channel, thread_ts=job.thread_ts,
                                    blocks=blocks.queued(job, pos, cfg.bot_name), text="Queued")
    except Exception:
        import traceback
        traceback.print_exc()


def main():
    missing = [k for k in ("slack_bot_token", "slack_app_token") if not getattr(cfg, k)]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(m.upper() for m in missing)}. See .env.example")
    if not cfg.repos:
        raise SystemExit("No repos configured. See config.example.yaml")
    jobq.start()
    print(f"{cfg.bot_name} is up. Mention the bot in Slack to report a bug or feature.")
    SocketModeHandler(app, cfg.slack_app_token).start()


if __name__ == "__main__":
    main()
