"""Slack Block Kit builders = the Fix Card, rendered as Slack messages.

Design rules:
- Plain language. The standard person never sees "merge", "rebase", "PR".
  Buttons are Accept / Reject. Engineer details live in a small footer.
- Always show an ETA: "Accept and this is live in ~8 min."
"""
from __future__ import annotations

from .models import FixResult, Job


def _btn(text: str, action_id: str, value: str, style: str | None = None) -> dict:
    b = {"type": "button", "text": {"type": "plain_text", "text": text, "emoji": True},
         "action_id": action_id, "value": value}
    if style:
        b["style"] = style
    return b


def _ctx(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def queued(job: Job, position: int, bot: str) -> list[dict]:
    line = "You're next up." if position <= 1 else f"You're *#{position}* in line."
    return [
        _section(f":eyes: Got it — *{bot}* is on the case. {line}"),
        _ctx(f"_{_short(job.description)}_"),
    ]


def working(job: Job, bot: str) -> list[dict]:
    return [_section(f":mag: Reproducing and fixing now… I'll post a before/after when it's ready.")]


def fix_card(job: Job, result: FixResult, eta_minutes: int, bot: str,
             needs_accept: bool = True) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text",
                  "text": _short(f"✅ Fixed: {result.plain_summary or job.description}", 148),
                  "emoji": True}},
        _section(f"*What was wrong*\n{result.what_was_wrong or '—'}"),
        _section(f"*What I changed*\n{result.what_changed or '—'}"),
    ]

    if result.before_video or result.after_video:
        blocks.append(_ctx(":movie_camera: Before & after clips attached above."))
    else:
        blocks.append(_ctx(":information_source: Before/after shown as text — add a repro hook for video."))

    checks = []
    checks.append(":white_check_mark: passed my own code review" if result.review_passed
                  else ":warning: review had notes")
    checks.append(":white_check_mark: tests green" if result.tests_passed
                  else ":warning: tests not fully green")
    blocks.append(_ctx(" · ".join(checks)))

    if needs_accept:
        blocks.append(_section(f":rocket: *Accept* and this is live in *~{eta_minutes} min*."))
        blocks.append({"type": "actions", "block_id": f"act_{job.id}", "elements": [
            _btn("✅ Accept", "accept", job.id, style="primary"),
            _btn("🗑 Reject", "reject", job.id, style="danger"),
            _btn("🙋 Send to a human", "to_human", job.id),
        ]})
    else:
        blocks.append(_section(f":rocket: Shipping automatically — live in *~{eta_minutes} min*."))

    # engineer-only footer
    foot = []
    if job.pr_url:
        foot.append(f"<{job.pr_url}|PR #{job.pr_number or '?'}>")
    if result.files_changed:
        foot.append(f"{len(result.files_changed)} file(s)")
    if result.root_cause:
        foot.append(f"root cause: {result.root_cause}")
    if foot:
        blocks.append(_ctx("for engineers · " + " · ".join(foot)))
    return blocks


def shipping(eta_minutes: int) -> list[dict]:
    return [_section(f":package: Accepted — rebasing on the latest, merging, and shipping. Live in ~{eta_minutes} min.")]


def live(job: Job) -> list[dict]:
    return [_section(":tada: *It's live.* Thanks for the report!"),
            _ctx(f"shipped from PR #{job.pr_number or '?'}" if job.pr_number else "shipped")]


def rejected() -> list[dict]:
    return [_section(":wastebasket: Tossed it — no changes shipped.")]


def deploy_failed(detail: str = "") -> list[dict]:
    out = [_section(":x: *Shipping hit a snag — nothing went live.* An engineer should take a look.")]
    if detail:
        out.append(_ctx("```" + _short(detail, 260) + "```"))
    return out


def escalation(job: Job, result: FixResult, engineer, team, bot: str) -> list[dict]:
    mentions = " ".join(m.slack for m in team)
    picked = engineer.slack if engineer else mentions
    notes = result.notes_for_human or "I couldn't get to a confident fix."
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
         "text": f"⚠ Needs a human: {_short(job.description)}", "emoji": True}},
        _section(f"*What I found*\n{notes}"),
        _section(f"Handing this to {picked} — first to grab it owns it. {mentions}"),
    ]
    if job.branch:
        blocks.append(_ctx(f"my draft work is on `{job.branch}` so you start from my progress, not zero"))
    blocks.append({"type": "actions", "block_id": f"esc_{job.id}", "elements": [
        _btn("🙋 I'll take it", "take_it", job.id, style="primary"),
        _btn("🔁 Try again with a hint", "try_again", job.id),
    ]})
    return blocks


def feature_card(job: Job, result: FixResult, bot: str) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text",
         "text": _short(f"✨ Mockup: {result.plain_summary or job.description}", 148), "emoji": True}},
        _section(f"*The idea*\n{result.what_changed or _short(job.description)}"),
        _ctx(":information_source: This is a mockup — nothing built yet. Tell me what to change."),
        {"type": "actions", "block_id": f"feat_{job.id}", "elements": [
            _btn("🛠 Build it for real", "build_real", job.id, style="primary"),
            _btn("✏️ Make it better", "make_better", job.id),
            _btn("🗑 Discard", "reject", job.id),
        ]},
    ]


def _short(text: str, n: int = 80) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"
