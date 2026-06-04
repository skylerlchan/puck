# Puck

A Slack bot that fixes your bugs and ships the fix — so the standard person never
has to touch GitHub. Someone reports a problem in Slack; the bot reproduces it,
fixes it, reviews its own work, and posts a **before/after with Accept / Reject**.
Tap **Accept** and it's live in a few minutes. Can't fix it? It hands off to an
engineer with its progress attached.

```
@Puck the login button does nothing on mobile

  🐛  Puck  APP
  ✅ Fixed: Login works on phones now
  What was wrong:  tapping Login did nothing — the tap wasn't reaching the button
  What I changed:  made the button tappable + added a test so it can't silently break
  ✓ passed my own code review · ✓ tests green
  🚀 Accept and this is live in ~8 min.
  [ ✅ Accept ]  [ 🗑 Reject ]  [ 🙋 Send to a human ]
```

## Where this runs

One **always-on worker** — your VM, a Mac mini, or a small cloud box. It:

1. Holds the Slack connection (**Socket Mode**, so no public URL / webhook to host).
2. Runs a **bug queue** — reports line up and are worked `concurrency` at a time.
3. For each job, creates an **isolated git worktree** off `main`, runs **Claude Code**
   in it to fix the bug, runs your tests, self-reviews, and opens a PR with `gh`.
4. On **Accept**, rebases on `main`, merges, and runs your deploy command — then
   posts "it's live."

Nothing runs on the reporter's machine. The worker needs: Python 3.12, the
`claude` CLI (logged in), the `gh` CLI (`gh auth login`), and your repo checked out.

```
Slack  ──mention──▶  worker (this bot)
                       │  enqueue → worktree off main
                       │  Claude Code: reproduce → fix → test
                       │  self-review (/code-review) → revise if needed
                       │  gh pr create
                       ▼
Slack  ◀─ Fix Card ──  Accept? → rebase + merge + deploy → "it's live"
                       Can't fix? → escalate to @skyler / @edison / @ben
```

## What it does for you

- **Plain language, no jargon.** Buttons are Accept / Reject. Rebase-with-main,
  merge, and deploy all happen under the hood — the reporter never learns what
  "merge" means. An engineer-only footer carries the PR link and root cause.
- **Tells you the ETA.** "Accept and this is live in ~8 min" (`deploy_eta_minutes`).
- **Reviews its own work before showing you.** A `/code-review`-style pass runs on
  the diff; if it finds must-fix issues it revises and re-tests (up to
  `review_max_rounds`) before ever surfacing Accept. Fails review → escalates.
- **Ships autonomously.** At `autonomy: auto` it skips the Accept tap for verified,
  low-risk fixes and just ships, posting for awareness.
- **Queues work.** Multiple reports at once → "you're #2 in line."
- **Knows its limits.** No confident fix, red tests, or failed review → it routes to
  a human (round-robin across your team) with its draft branch + notes, so they
  start from its progress, not zero.
- **Features too.** Mention an idea and `@featurebot` builds a quick prototype with
  **Build it for real / Make it better / Discard**.

## Setup

```bash
cd puck
pip install -r requirements.txt          # slack-bolt, slack-sdk, pyyaml
cp .env.example .env                      # add your two Slack tokens
cp config.example.yaml config.yaml        # set repo path, team, autonomy
gh auth login                             # the bot opens/merges PRs as you
# claude   (make sure Claude Code is installed + logged in)

set -a; source .env; set +a
python app.py
```

### Slack app (one-time)

At <https://api.slack.com/apps> → create an app:
- **Socket Mode**: on → create an App-Level Token with `connections:write` → `SLACK_APP_TOKEN`.
- **OAuth scopes** (Bot): `app_mentions:read`, `chat:write`, `files:write`, `commands` (optional).
- **Event Subscriptions** → subscribe to `app_mention` (and `message.channels` if you
  want mention-free intake — see `on_message` in `app.py`).
- Install to the workspace → copy the **Bot User OAuth Token** → `SLACK_BOT_TOKEN`.
- Invite the bot into `#bugs` and `#features`.

## Try it locally right now (no Slack, no GitHub)

Local mode fixes a bug in any local git repo using your `claude` CLI, runs your
tests, reviews its own diff, and hands you the diff + a branch. Nothing is pushed.

```bash
python -m puck.cli --local /path/to/repo "the subtract function returns the wrong answer" \
  --test-cmd "pytest -q"
```

Other entry points:

```bash
python -m puck.cli --mock                      # render a sample Fix Card, no deps
python -m puck.cli "the X button is broken"    # full pipeline (needs config + gh)
pytest -q                                      # unit tests
```

## The hidden screen (where it works unseen)

Puck can reproduce and record bugs on a screen you never see. Two tiers — full
design + verified sources in [docs/hidden-screen-architecture.md](docs/hidden-screen-architecture.md):

- **Tier 1 — headless browser** (web-app bugs): a headless Chromium context renders
  the real app offscreen; Puck drives the failing flow and records before/after
  video. Just write a repro hook — see [examples/repro_playwright.py](examples/repro_playwright.py).
- **Tier 2 — virtual desktop** (anything with a GUI): a full **Linux desktop in
  Docker** the agent controls like a human — mouse, keyboard, screenshots, video —
  via Anthropic computer use. Launch it with one command and optionally watch via
  noVNC: [vd/README.md](vd/README.md). It controls the container's screen, not your
  macOS GUI (the honest limit).

## Autonomy levels (`config.yaml`)

| `autonomy` | Behavior |
|---|---|
| `suggest` | Posts a plan only |
| `propose` | Builds the fix + opens a PR; **a human taps Accept** *(default)* |
| `auto` | Ships verified, low-risk fixes itself |
| `workflow` | Whole classes of problems fixed end-to-end |

Start at `propose`. Move an area to `auto` once you trust it.

## Before/after video

Real video needs a per-repo **repro hook** — a script that drives the failing
scenario. Set `repro:` in `config.yaml`; the bot runs it on `main` (before) and on
the fix branch (after), each writing to `$PUCK_RECORD_OUT`, and attaches both clips.
No hook configured → the card shows a text before/after instead (never a fake clip).
Playwright (`page.video`) is the easy way to produce the recordings.

## Layout

```
app.py                  Slack entrypoint (Socket Mode) + button handlers
puck/
  config.py             YAML + env config
  models.py             Job, FixResult, Status
  queue.py              the bug queue + worker threads
  fixer.py              the pipeline: fix → test → review → PR → ship
  claude_runner.py      Claude Code CLI wrapper
  github_ops.py         git worktrees + gh (PR, rebase, merge, deploy)
  review.py             self-review (/code-review) pass
  recorder.py           optional before/after capture
  blocks.py             the Fix Card as Slack Block Kit (Accept/Reject/ETA)
  store.py              job state + round-robin escalation
  notify.py             Slack vs Console notifier
  cli.py                local dry-run
tests/                  unit tests (no Slack/Claude/gh needed)
```

## Safety notes

- Every fix runs in a throwaway worktree, so `--dangerously-skip-permissions` only
  ever touches an isolated copy — never your real working tree.
- The bot acts as whoever ran `gh auth login`. Use a dedicated bot GitHub account if
  you don't want PRs/merges attributed to a person.
- Branch protection still applies — if `main` requires checks, the merge waits on them.
