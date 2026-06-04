# Slack → Autonomous Bug-Fix → GitHub PR: Tool Landscape & Build Sketch

*Created 2026-06-04 12:33. Deep-research pass, 21 sources fetched, 25 claims adversarially fact-checked (22 confirmed / 3 killed).*

## The question

Is there a tool where you drop a bug into a Slack channel — ideally a **screen recording / screenshot** of the failure plus a description of expected behavior — and an agent investigates, asks clarifying questions, fixes it autonomously, opens a GitHub PR with tests, and shows a before/after?

## Headline

The *workflow* exists and is shipping in 2025–2026. The *distinctive part of your idea — dropping a screen recording/video of the failure as the bug spec — is met by none of the verified tools.* Everything that takes multimodal input today takes **still screenshots only**, not video. That gap is your wedge if you build.

## Recommendation matrix (verified tools only)

| Tool | Slack trigger | Multimodal intake | Investigates / asks Qs | Opens GitHub PR | Tests | Notes |
|---|---|---|---|---|---|---|
| **GitHub Copilot coding agent** | Yes — `@GitHub` in any Slack thread | No (text prompt) | Background work, posts plan | Yes, link back to thread | Can run CI | GitHub-first, cleanest off-the-shelf path. Public preview; needs paid Copilot + coding agent enabled ([GitHub changelog, 2025-10-28](https://github.blog/changelog/2025-10-28-work-with-copilot-coding-agent-in-slack/); [GitHub docs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/integrate-cloud-agent-with-slack)) |
| **Charlie Labs** | Yes — `@Charlie` in Slack | **Images/screenshots only** (Sep 2025) | Yes — root-cause from Sentry+GitHub+Linear | Yes — branch+commit+PR back to thread | Configurable "PR must include passing tests" | Closest single product to the full ask short of video ([charlielabs.ai](https://charlielabs.ai/); [changelog](https://charlielabs.ai/changelog/); [GitHub integration docs](https://docs.charlielabs.ai/integrations/github)) |
| **Continue Slack Cloud Agent** | Yes — `@Continue` / report a bug | No (screen-recording claim was *refuted*) | Connects to GitHub, locates files | Yes — new branch + auto-PR | — | Slack app in beta ([Continue blog](https://blog.continue.dev/slack-cloud-agent-github-linear); [docs](https://docs.continue.dev/mission-control/integrations/slack)) |
| **Sentry Seer / Autofix** | "Fix with Seer" on alerts | No (text telemetry only) | Yes — root cause from traces/logs/code | Yes (configurable) **and can hand off to Claude Code or Cursor Cloud Agents** | — | GitHub-first, but triggers from a **Sentry error event, not a free-form bug report** ([Autofix docs](https://docs.sentry.io/product/ai-in-sentry/seer/autofix/); [Claude Code handoff](https://docs.sentry.io/integrations/coding-agents/claude/)) |
| **Replay.io** | No | **Recording, but it captures, not ingests** | Provides root cause to agent | Via the agent it feeds | — | Deterministic browser recording exposed to Claude Code/Cursor/Copilot over **MCP**. Best "reproduction" building block ([how-it-works](https://www.replay.io/how-it-works); [MCP docs](https://docs.replay.io/basics/replay-mcp/overview)) |

### The multimodal gap (the important finding)

- **Charlie** added image understanding 2025-09-30 — it reads screenshots in Slack/Linear/GitHub and references them in plans/PRs — but **no video/screen-recording support** is documented ([Charlie changelog: Image Understanding](https://www.charlielabs.ai/changelog?entry=2025-09-30-image-understanding)).
- **Sentry Seer** takes only textual telemetry; Session Replay video is for *humans to watch*, not Seer intake ([Autofix docs](https://docs.sentry.io/product/ai-in-sentry/seer/autofix/)).
- **Replay.io** captures a *live* deterministic session via a Chrome extension/CLI — it does **not** ingest a pre-recorded `.mp4`/`.mov` you upload ([Replay how-it-works](https://www.replay.io/how-it-works)).
- One lead worth a separate look: **Replay.build** (a *different* company, Gemini-powered) reportedly accepts uploaded Loom/OBS recordings → code. Not verified here; flagged as the single closest match to the video-intake idea.

## Build-it-yourself: what those teams did

You're on GitHub and already use Claude Code, so a DIY version is very feasible. The reference stack:

| Component | Forkable reference |
|---|---|
| **Slack → Claude Code → GitHub PR, end-to-end** | [`MattKilmer/claude-autofix-bot`](https://github.com/MattKilmer/claude-autofix-bot) — bug in Slack → 👀 reaction → Claude Code CLI (`--output-format=stream-json`) → semantic branch → commit/push → `octokit.pulls.create` → PR link back to thread. **Image intake only; no license file; early (~3 commits).** Closest fork target. |
| **Official GitHub Action** | [`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action) + [Claude Code GitHub Actions docs](https://code.claude.com/docs/en/github-actions) |
| **Claude Code ↔ Slack bot** | [`AnandChowdhary/claude-code-slack-bot`](https://github.com/AnandChowdhary/claude-code-slack-bot) |
| **Sandboxed/containerized runs** | [`ghostwriternr/claude-code-containers`](https://github.com/ghostwriternr/claude-code-containers); [`SWE-agent/SWE-ReX`](https://github.com/SWE-agent/SWE-ReX) for sandboxed execution |
| **Open-source async coding agent (whole loop)** | [LangChain Open SWE](https://www.langchain.com/blog/introducing-open-swe-an-open-source-asynchronous-coding-agent) |
| **Rich runtime reproduction context for the agent** | [Replay MCP](https://docs.replay.io/basics/replay-mcp/overview) — gives Claude Code deterministic runtime trace + root cause |
| **Before/after verification artifacts on the PR** | [`AmElmo/proofshot`](https://github.com/AmElmo/proofshot) — records the *agent's* browser session, bundles screenshots+video+errors into a proof artifact on the PR |

### Sketch of the loop to build

1. **Slack Events API** listener on a channel; on a message with attachments + text, react 👀.
2. **Multimodal intake (your wedge):** Claude can read images natively. For a screen recording, extract keyframes (ffmpeg) → feed frames to Claude, or transcribe the recording's events. (No off-the-shelf tool does this today — this is the differentiator.)
3. **Clarify:** if expected-vs-actual is ambiguous, reply in-thread with questions before acting.
4. **Reproduce:** spin a sandboxed checkout (container); optionally attach Replay MCP for a deterministic runtime trace.
5. **Plan → patch → test:** Claude Code CLI/Agent SDK edits, runs the test suite, iterates until green.
6. **PR:** create branch + PR via Octokit; post the link + a before/after (ProofShot-style) back to the thread.

## Build vs buy

- **Want it working this week, no video:** turn on **GitHub Copilot coding agent in Slack** (you're GitHub-first) or trial **Charlie Labs** (closest to the full flow, takes screenshots).
- **Want the screen-recording intake that nobody ships:** build it — fork `claude-autofix-bot` for the Slack↔Claude Code↔PR plumbing, add the video→keyframes→Claude step yourself, bolt on Replay MCP + ProofShot. That multimodal intake is genuinely novel.

## Caveats & gaps

- **No verified tool accepts a user-uploaded screen recording as bug intake.** That's the consistent finding.
- **Devin, Cursor background agents/Bugbot, Codegen, Factory.ai droids, Sweep, Greptile, Graphite Diamond, Tembo** were in scope but **no claims about them survived 3-vote verification** — treat their capabilities as unconfirmed here, not as absent. Factory.ai's Slack-trigger and PR-from-plain-English claims were *specifically refuted* and need fresh primary-source checking.
- Most capability evidence is **first-party (vendor docs/blogs)**. Copilot, Charlie, and Replay have some independent corroboration.
- **Time-sensitive:** Copilot's Slack integration (Oct 2025) and Charlie's image support (Sep 2025) are recent/preview; a video feature could land on any of these without notice.
