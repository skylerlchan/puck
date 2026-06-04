# Fix Bot — Slack-native autonomous bug & feature agent

*Created 2026-06-04. Master product spec. Supersedes the web-UI framing in [fix-card-pr-artifact.md](fix-card-pr-artifact.md) — that card is now the **content of a Slack message**, not a separate app.*

> **Built:** a working implementation lives in [`puck/`](../../puck/) (Python, Socket Mode). Decisions locked in since the first draft:
> - Buttons are **Accept / Reject**, not Merge — rebase-on-main + merge + deploy are hidden. The card shows an **ETA** ("live in ~8 min").
> - A **self-review** (`/code-review`) pass runs on every diff before Accept appears; failed review → escalate.
> - A real **bug queue** ("you're #2 in line") with N-at-a-time workers.
> - Runs on **one always-on worker**; each fix in an isolated git worktree.
> - **Autonomy ladder** dials whether Accept is required or it ships itself.

## The shift

There is **no separate UI to build**. The product lives entirely in Slack. Anyone reports a
problem in a channel; the bot does the work and replies **in the thread** with proof + buttons.
Slack Block Kit *is* the interface — that's the whole point: nothing new for anyone to learn.

## The core loop

1. **Report** — someone posts a problem to `#bugs` (or `@bugbot`): a sentence + optional screenshot.
2. **Acknowledge** — bot reacts 👀, replies "on it," asks a clarifying question only if it must.
3. **Reproduce** — bot spins a sandbox on `main`, reproduces the bug, **records a "before" video**.
4. **Fix** — agent patches on a branch, runs tests until green.
5. **Prove** — re-runs the same scenario on the fix branch, **records an "after" video**.
6. **Post** — replies in-thread with: before video · after video · one-line "what was wrong / how I fixed it" · safety line (tests/scope/risk) · **action buttons**.
7. **Decide** — a human taps **Merge** (or Ask / Send to engineer / Reject) — right in Slack.
8. **Escalate** — if it can't reproduce or fix, or tests stay red, it routes to a human instead (see below).

## The Slack thread (what the message looks like)

```
@bugbot  🐛 Fixed: "Login button does nothing on mobile"   ✓ verified
─────────────────────────────────────────────
▶ Before (0:06)   the tap does nothing, no request fires
▶ After  (0:05)   tap submits → redirects to dashboard
─────────────────────────────────────────────
Root cause: an overlay was capturing the tap on touch devices.
Fix: lowered overlay z-index + pointer-events:none.  2 files · +12 −6
Tests: 142 passed · 1 added · suite green · no risk flags
─────────────────────────────────────────────
[ ✅ Merge ]  [ 🔁 Ask / revise ]  [ 👤 Send to engineer ]  [ ❌ Reject ]
```

The message fields map 1:1 to the `FixCard` schema in
[fix-card-pr-artifact.md](fix-card-pr-artifact.md) — same data, rendered as Slack blocks instead
of HTML. Merge button → calls GitHub API to merge the PR; result posts back to the thread.

## Before / after VIDEO (the new requirement)

This is generatable, no human recording needed:
- **Before** = run the reproduction steps in a headless browser **on `main`**, record the session.
- **After** = run the *same* steps on the fix branch, record again.
- Same script, two checkouts, two clips → a true side-by-side of baseline vs fixed.

Grounded in real building blocks from the landscape research: Playwright records browser video
out of the box, and [`AmElmo/proofshot`](https://github.com/AmElmo/proofshot) already records an
agent's browser session and bundles video+screenshots onto a PR. For non-UI bugs the "video"
degrades gracefully to a terminal/test-output recording (asciinema-style) or a before/after value.

## Two accounts

| | `@bugbot` | `@featurebot` |
|---|---|---|
| Input | "X is broken" | "I wish it did Y" |
| Output | before/after video of the **fix** | before/after video of a **mockup** of the feature |
| Loop | reproduce → fix → prove → merge | mock it up → "make it better" iterations → on approval, build → PR |
| Channel | `#bugs` | `#features` |

For `@featurebot`, the "after" video is a **prototype** of the requested feature so people can
see it and refine ("make the button bigger," "move it left") before any real build happens.

## Escalation — the team safety net

If the bot can't reproduce, can't fix, tests stay red, or confidence is low, it does **not** guess.
It posts what it found and where it got stuck, then routes to a human:

```
@bugbot  ⚠ Couldn't auto-fix: "Checkout total is wrong for EU VAT"
Here's what I found: [root-cause attempt] · [repro that half-works]
Routing to an engineer →  @skyler  @edison  @ben
[ 🙋 I'll take it ]
```

- Round-robin or @here across **Skyler, Edison, Ben**; first to tap "I'll take it" owns it.
- The bot's partial work (repro, suspected root cause, branch) is handed to whoever picks it up,
  so they start from the bot's progress, not zero.

## Autonomy ladder (dial per channel / per repo)

| Level | Behavior | Use for |
|---|---|---|
| **L0 Suggest** | Posts plan only; human builds | risky repos |
| **L1 Propose** | Builds + posts PR with before/after; **human merges** | *default — what we're building* |
| **L2 Auto-merge** | Auto-merges verified, low-risk fixes; posts for awareness | trivial/low-risk classes |
| **L3 Workflow** | Whole classes of reported problems fixed end-to-end, fully autonomous | mature, well-tested areas |

Start at **L1**. Earn L2/L3 per area as trust builds.

## What we keep / drop from the earlier design

- **Keep:** the `FixCard` content model, the "safety panel → button state" logic, before/after proof.
- **Drop:** the standalone web UI. Slack renders it.
- **Add:** generated before/after **video**, in-thread merge, human **escalation**, bug vs feature personas, the autonomy ladder.

## Open decisions to refine
- **Merge target:** does Merge merge the PR directly, or open it for normal GitHub review first?
- **"Ask / revise":** revise in the same thread (edit the message) or post a v2 reply?
- **Escalation routing:** round-robin, load-based, or @here free-for-all?
- **Video length/host:** cap clip length; upload to Slack directly vs link out (Slack file size limits).
- **Feature mockups:** how real is the prototype — clickable preview, or just a rendered screen/video?
