# Puck — Hidden Screen (Tier 2: Virtual Desktop)

Puck works on a part of your computer you don't see. There are two tiers; pick by
what the bug lives in. Full design + verified sources: [../docs/hidden-screen-architecture.md](../docs/hidden-screen-architecture.md).

| | Tier 1 — Headless Browser | Tier 2 — Virtual Desktop (this folder) |
|---|---|---|
| Hidden screen | a headless Chromium context | a full **Linux desktop in Docker** (Xvfb) |
| Controls | the browser DOM | mouse, keyboard, **any app** — like a human |
| Bug type | web-app bugs | anything with a GUI; cross-app flows |
| Speed | fast, deterministic | slower (a model round-trip per step) |
| Build | write a repro hook ([../examples/repro_playwright.py](../examples/repro_playwright.py)) | `docker compose up` (below) |

## See it right now

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose -f vd/docker-compose.yml up      # first run pulls the image
```

Then open **http://localhost:8080** — chat on the left, the **live hidden desktop**
on the right. Ask it to "open Firefox and search for X" and watch it move the
mouse, type, and click. That desktop is running entirely inside the container;
your Mac screen is untouched. Stop with `docker compose -f vd/docker-compose.yml down`.

## How it actually controls the screen

It's an **application-driven agent loop** (verified against Anthropic's docs):

1. Claude returns a `tool_use` block (e.g. `left_click [x,y]`, `type "hello"`, `screenshot`).
2. The container executes it with `xdotool` / `scrot` against the **virtual X display**.
3. The resulting screenshot (base64 PNG) goes back as a `tool_result`.
4. Repeat until the task is done.

Anthropic never touches your machine — your container runs every action locally
(the feature is Zero-Data-Retention eligible). It needs the beta header
`computer-use-2025-11-24` (current for Opus 4.8 / 4.7 / 4.6, Sonnet 4.6, Opus 4.5).

## What is and isn't possible (be honest)

- ✅ A hidden Linux desktop the agent fully drives — type, click, screenshot, record.
- ✅ Runs locally on your Mac; you can watch via noVNC or stay out of it entirely.
- ❌ It is **the container's Linux screen, not your macOS GUI.** Controlling the real
  Mac desktop invisibly is not possible without a separate machine/VM (a hidden
  *macOS* guest needs Lume or `trycua/cua` — a heavier path, noted in the doc).
- ⚠️ Slower than Tier 1 (model round-trip per step) and costs scale with screenshots
  (~1–1.8k tokens each). Mitigate with prompt caching + screenshot pruning.
- ⚠️ Computer use is still **beta**, and prompt-injection is a real risk — keep the
  container credential-free and domain-allowlisted; **Accept** stays the human gate.

## Wiring it into Puck's pipeline (the seam)

The hidden screen only plugs into the **record step** of the fix pipeline
([../puck/fixer.py](../puck/fixer.py) `run_job`) — fix / test / review / PR / ship
are untouched. A Tier-2 repro hook honors the same contract as Tier 1
(`$PUCK_RECORD_OUT`, `$PUCK_LABEL`): record the container's framebuffer to video
(`ffmpeg -f x11grab -i :1`) while the computer-use loop drives the scenario.
Forkable starting point for the loop: `anthropic-quickstarts/computer-use-demo`
(`computer_use_demo/loop.py`). This is the documented next build step — the
container above already lets you *use* the capability today.
