# Puck — Hidden Screen Architecture

_Created 2026-06-04 15:34 PDT_

How Puck (the autonomous bug-fixer in this repo, package `puck/`) gets a
screen it **fully controls** — screenshots, video, typing, clicking — that the
user **never sees take over their Mac**. Two tiers, both local, no cloud:

| Tier | Hidden screen | Drives it | Ships |
|---|---|---|---|
| **1 — Headless Browser Stage** | Chromium offscreen (Playwright headless) | deterministic script | today |
| **2 — Virtual Desktop Stage** | full Linux desktop in Docker (Xvfb + VNC) | Anthropic **computer use** (the model clicks/types) | next |

The key constraint up front, so nothing downstream is a surprise: **the screen
Puck controls invisibly is a virtual display it owns — a headless
Chromium context (Tier 1) or the container's Linux X11 display (Tier 2). It is
never the macOS GUI.** Driving the real Mac desktop invisibly is impossible
(see [Honest limits](#6-honest-limits)). That is a feature: the user's actual
screen, mouse, and keyboard are untouched while Puck works.

---

## 0. Where this plugs into the existing pipeline

Today's pipeline (`puck/fixer.py:run_job`) is:

```
queue → worktree off main → Claude Code fixes → tests → self-review (/code-review)
      → [record before/after] → PR → Fix Card (Accept/Reject) → ship (rebase+merge+deploy)
```

The hidden screen lives **only inside the `[record before/after]` step** and a new
optional **repro/verify** capability. The fix engine (Claude Code editing files in
a git worktree) is unchanged. The seam already exists:

- `puck/recorder.py:record_before_after(repro_command, base_checkout, fix_worktree)`
  runs a per-repo hook on the base checkout (BEFORE, buggy) and the fix worktree
  (AFTER, fixed), returning `(before_video, after_video)` paths.
- The hook contract is **`$PUCK_RECORD_OUT`** (file the hook must write — mp4/gif/png)
  and **`$PUCK_LABEL`** (`before` / `after`). Capture counts only if the hook exits
  `0` **and** the file is non-empty (`recorder.py:_capture`). Otherwise → `None` and
  the card degrades to a text before/after (never a faked clip).
- `RepoCfg.repro` (`puck/config.py`) wires the hook in via `config.yaml`.

**Both tiers produce exactly these two artifacts** (`before_video`, `after_video`)
and flow through the unchanged `fixer.py` lines 142–166 (capture → `upload_video`
→ `fix_card`). Tier 1 reuses the `repro:` hook as-is. Tier 2 adds a parallel
`vd:` (virtual-desktop) hook that emits the same outputs. No change to queue,
review, PR, or ship.

---

## 1. TIER 1 — Headless Browser Stage (ship today)

**The hidden screen is a headless Chromium browser context.** It renders the web
app fully (real DOM, real paint, real video frames) but to an offscreen surface —
nothing appears on the Mac. This is the right tool for **web-app bugs**, which are
the bulk of "the login button does nothing" reports.

### What it does

1. **Reproduce** the reported bug by driving the failing user flow in headless
   Chromium against a locally-served build of the app.
2. **Record a BEFORE clip** by running that same flow against the checkout of
   `main` (the buggy base worktree, `gh.prepare_base_worktree`).
3. **Record an AFTER clip** by running it against the fix branch worktree.
4. **Capture screenshots** at assertion points (e.g. the moment of the broken
   click) for the Fix Card and the PR body.

Playwright records video per `BrowserContext` (`page.video`) and screenshots per
`page` — both write files, which is exactly what `$PUCK_RECORD_OUT` wants.

### Repro-hook contract (Tier 1)

The hook is **any executable** the repo owner commits. Puck guarantees:

| Env var | Meaning |
|---|---|
| `PUCK_RECORD_OUT` | absolute path the hook MUST write the clip to (`.mp4` recommended) |
| `PUCK_LABEL` | `before` or `after` — same scenario, run twice |
| _cwd_ | the checkout being tested (base worktree for `before`, fix worktree for `after`) |

Contract: exit `0` and write a non-empty file → counts as a clip. Anything else →
ignored (degrades to text). Timeout 600s (`recorder.py`). The hook is responsible
for **starting the app under test** in its own cwd (e.g. `npm run dev &` on a
random port) so BEFORE runs the buggy code and AFTER runs the fixed code.

`config.yaml`:

```yaml
repos:
  default:
    repro: "node tools/puck/repro.mjs"   # the hook below
```

### Minimal hook sketch (`tools/puck/repro.mjs`)

```js
// Reused for BEFORE (in main's checkout) and AFTER (in the fix worktree).
// Puck sets PUCK_RECORD_OUT + PUCK_LABEL and runs us in that checkout.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdtempSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const OUT  = process.env.PUCK_RECORD_OUT;            // where the clip must land
const PORT = 3000 + Math.floor(Math.random() * 1000);

// 1. boot THIS checkout's app (buggy on main, fixed on the branch)
const app = spawn('npm', ['run', 'dev', '--', '--port', String(PORT)],
                  { stdio: 'ignore', env: { ...process.env, PORT: String(PORT) } });
await waitForPort(PORT);                              // poll until 200

// 2. drive the failing flow with video recording on
const videoDir = mkdtempSync(join(tmpdir(), 'shake-vid-'));
const browser  = await chromium.launch();            // headless: the hidden screen
const ctx      = await browser.newContext({ recordVideo: { dir: videoDir, size: { width: 1280, height: 800 } } });
const page     = await ctx.newPage();

await page.goto(`http://localhost:${PORT}/login`);
await page.getByRole('button', { name: 'Login' }).click();   // the reported bug
// AFTER this assertion passes; BEFORE it (harmlessly) does nothing visible
await page.waitForURL('**/dashboard', { timeout: 8000 }).catch(() => {});
await page.screenshot({ path: OUT.replace(/\.mp4$/, '.png') });

// 3. hand Puck the clip at exactly PUCK_RECORD_OUT
await ctx.close();                                   // flushes the video file
copyFileSync(await page.video().path(), OUT);
await browser.close(); app.kill();
```

`fixer.py:144–146` runs this for BEFORE on a base worktree and AFTER on the fix
worktree; `notifier.upload_video` attaches both to the card.

### Why Tier 1 first

- **Deterministic and fast** — no model in the capture loop, so clips are cheap and
  repeatable. Per the latency finding, you do **not** want a model round-trip per
  click just to record a known flow.
- **Already wired** — `recorder.py` + `RepoCfg.repro` exist; Tier 1 is "write the
  hook," zero engine changes.
- **Covers the common case** — most reports in `#bugs` are web UI.

**Limit:** Tier 1 only does what the *script* says. It can't improvise on an
unknown UI or fix native/desktop apps. That's Tier 2.

---

## 2. TIER 2 — Virtual Desktop Stage (the impressive one)

**The hidden screen is a full Linux desktop running inside a Docker container on
the Mac.** Puck drives it with **Anthropic computer use** — the model
*looks at a screenshot and decides where to click/type*, the agent loop executes
the action against the container, screenshots the result, and repeats. This
handles bugs where there's no pre-written script: unfamiliar UIs, multi-app flows,
"figure out how to reproduce this."

The user sees nothing. The desktop lives on the container's **virtual X11
framebuffer (Xvfb)** — there is no monitor attached. The user can *optionally*
peek via noVNC in a browser tab, but by default it runs invisibly.

### 2.1 The container

Fork the official reference: **`anthropics/anthropic-quickstarts`**, subdir
`computer-use-demo`. It is a self-contained virtual desktop:

- Base `ubuntu:22.04`, non-root user `computeruse` (passwordless sudo), Python
  3.11 via pyenv.
- **Xvfb** — virtual X11 framebuffer (the hidden screen, default `1024x768`,
  `DISPLAY_NUM=1`; resizable via `WIDTH`/`HEIGHT` build args).
- **Mutter** window manager + **Tint2** panel — a real desktop env.
- **x11vnc** + **noVNC 1.5.0** / **websockify 0.12.0** — optional browser-based
  viewing of that framebuffer.
- **xdotool / scrot / imagemagick** — the actual mouse/keyboard control and
  screenshot capture the computer tool calls.
- Apps: Firefox-ESR, LibreOffice, gedit, xpdf, etc.
- `computer_use_demo/`: `computer.py` (computer tool → xdotool/scrot),
  `bash.py`, `edit.py`, `loop.py` (the agent loop), `streamlit.py` (chat UI).
- `image/entrypoint.sh` → `start_all.sh` (Xvfb, Tint2, Mutter, x11vnc) →
  `novnc_startup.sh` → `http_server.py` (combined `:8080` page) → Streamlit `:8501`.

Run it locally:

```bash
docker run \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v $HOME/.anthropic:/home/computeruse/.anthropic \
  -p 5900:5900 -p 8501:8501 -p 6080:6080 -p 8080:8080 \
  -it ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest
```

Ports: **5900** direct VNC, **6080** noVNC web (`/vnc.html`), **8501** Streamlit
chat, **8080** combined chat+desktop (the human-peek entry point).

> **Apple Silicon note:** the image is x86 Linux, so on M-series Macs it runs under
> emulation (slower). Fine for background fix-verification; don't expect snappy
> interaction. Bedrock/Vertex also work via `API_PROVIDER`. Only an API key is
> needed — no Claude.ai/Pro subscription.

### 2.2 How the model controls the screen — the agent loop

Computer use is **application-driven**: Anthropic never touches the container. Your
code runs the loop (this is `loop.py` in the fork; Puck calls it headlessly,
without Streamlit):

```
1. POST /v1/messages with the three tools + beta header
2. Claude replies with tool_use blocks, stop_reason="tool_use"
       e.g. { action: "left_click", coordinate: [512, 380] }
3. Your code runs it in the container (xdotool), takes a screenshot (scrot)
4. Return a tool_result with the base64 PNG screenshot
5. Repeat until Claude replies with no tool_use → task done
```

The model only ever sees screenshots and sends actions during the live API call
(ZDR-eligible, client-side tool). **The screen is the container's Xvfb display.**

#### Tools and headers (current, mid-2026)

Send all three tools; the beta header is required only because the `computer`
tool is present:

| Tool | type | name |
|---|---|---|
| computer | `computer_20251124` | `computer` |
| text editor | `text_editor_20250728` | `str_replace_based_edit_tool` |
| bash | `bash_20250124` | `bash` |

```python
# Pin to the current Opus line. The beta header gates which models are allowed.
BETA_HEADER = "computer-use-2025-11-24"        # → Opus 4.8/4.7/4.6, Sonnet 4.6, Opus 4.5
tools = [
    {"type": "computer_20251124", "name": "computer",
     "display_width_px": 1024, "display_height_px": 768, "display_number": 1,
     "enable_zoom": True},                      # zoom action: inspect a region 1:1
    {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
    {"type": "bash_20250124", "name": "bash"},
]
# computer tool is schema-less (baked into the model). Actions: screenshot,
# left_click, type, key, mouse_move, scroll, *_click, *_click_drag,
# left_mouse_down/up, hold_key, wait, and zoom (needs enable_zoom). Modifier
# keys ride along as a `text` param on click/scroll.
```

> If you must run an older model, use beta header `computer-use-2025-01-24` /
> tool `computer_20250124` / editor `text_editor_20250124` / bash `bash_20241022`
> (Sonnet 4.5, Haiku 4.5, Opus 4.1). The `computer_20241022` line served 3.5/3.7.

#### Thinking + cost knobs (from the findings)

- Thinking effort: **Opus 4.7 → `high`** (`low` if cost-sensitive); Sonnet 4.6 /
  Opus 4.6 → `medium`.
- **Screenshots dominate cost** (~1,000–1,800 input tokens each, one+ per turn).
  Tool overhead is small (~466–499 tokens for the beta system prompt, ~735 for the
  computer tool def). Mitigations, both in the loop:
  - **Prompt caching** — `cache_control` breakpoint after system+tools, advance it
    onto recent `tool_result`s.
  - **Prune old screenshots** — keep the last ~3, prune in batches every ~25 turns
    so the cache prefix stays stable.

#### Coordinate scaling gotcha

The API downsizes images over **1568px long edge / ~1.15MP**, so coordinates must
match the sent image. The container is set small (1024×768) specifically to dodge
this. **Opus 4.8/4.7 support up to 2576px long edge with 1:1 coordinates** — if you
size Xvfb up to retina-ish resolutions, pin to that model line so you don't have
to rescale. (This is also why you do *not* try to feed it a macOS Retina 2× DPR
screenshot — wrong tool, wrong screen; see limits.)

### 2.3 How Puck dispatches a job to the container

Puck stays the orchestrator; the container is a disposable worker it talks
to over HTTP. Add a thin **job server** to the fork (run alongside, not via
Streamlit) so `recorder.py` can drive it like any other repro hook.

```
fixer.py (host)                         puck-vd container (Docker)
  │  POST /vd/run                          ┌─ job server (FastAPI :9000)
  │    { repo_tarball | git_url,           │     mounts the worktree read-only
  │      branch, goal, label, out }   ───▶ │     starts the app under test
  │                                        │     runs the computer-use agent loop:
  │                                        │       "reproduce <goal>, record it"
  │  ◀── { ok, video_path, shots[] } ──────┤     ffmpeg-records Xvfb the whole time
  └─ copies clip to $PUCK_RECORD_OUT       └─ returns the mp4 + screenshots
```

**Dispatch mechanics:**

1. **Get code in.** Mount the git worktree into the container (`-v
   <worktree>:/workspace:ro`) or send a tarball. BEFORE → main's base worktree;
   AFTER → the fix worktree. Same two-run structure as Tier 1.
2. **State the goal in natural language**, not a script: e.g. _"Open the app at
   localhost:3000, sign in, and try to use the Login button; reproduce the
   reported failure."_ The model figures out the clicks. This is the qualitative
   leap over Tier 1.
3. **Run the loop** inside the container against its own Xvfb display.
4. **Return artifacts** — the mp4 and key screenshots — to the host, which writes
   the clip to `$PUCK_RECORD_OUT`.

So Tier 2 is just **another repro hook** from `fixer.py`'s point of view. Add a
sibling config field and let the host hook shell out to the container:

```yaml
repos:
  default:
    repro: null                       # Tier 1 (deterministic) — unused for VD jobs
    vd:                               # Tier 2 (virtual desktop, computer use)
      image: "puck-vd:latest"  # your fork of computer-use-demo
      goal_from: "description"        # use the Slack bug text as the agent goal
      headless: true                  # do NOT publish :6080 unless peeking
```

The host-side `vd` hook honors the **same `$PUCK_RECORD_OUT` / `$PUCK_LABEL`
contract**, so `recorder.record_before_after` and `fixer.py:142–166` need **no
changes** — it copies the container's mp4 to `PUCK_RECORD_OUT` and exits 0.

### 2.4 How screenshots + video are produced

- **Screenshots:** the computer tool itself (`scrot` via `computer.py`) every turn —
  these are what the model reasons over, and the salient ones get attached to the
  card / PR.
- **Video:** record the Xvfb framebuffer for the whole session with `ffmpeg
  -f x11grab -i :1 ...` (or screen-record noVNC). The loop's per-turn screenshots
  are for the model; the ffmpeg capture is the continuous BEFORE/AFTER clip the
  human watches.

### 2.5 EXACTLY what is and isn't possible (Tier 2)

**Possible — invisibly, on the Mac:**

- Full control of a **Linux desktop**: browse, click anything, type, drag, scroll,
  use Firefox/LibreOffice/any Linux app, run shell commands (bash tool), edit files
  (text-editor tool). Continuous video + per-step screenshots.
- The model **improvises** on UIs it's never seen — no pre-written script.
- Runs with **nothing on the user's monitor**; optional noVNC peek at `:6080`.

**NOT possible:**

- ❌ Controlling the **macOS GUI** — the controlled screen is the container's Linux
  X11 display, full stop. Computer use here drives Xvfb, not Aqua. There is no
  Mac-native click/type happening.
- ❌ Driving the **real Mac desktop invisibly** — macOS has one foreground GUI
  session tied to the physical display/login. Anything that automates the real
  Mac UI (Accessibility API, CGEvent, AppleScript UI scripting) **moves the user's
  actual cursor on their actual screen**, which violates the "don't take over the
  visible desktop" requirement. Doing this invisibly needs a **separate machine or
  a real macOS VM** with its own headless display — explicitly out of scope for a
  single local Mac.
- ❌ Testing a **Mac-only native app** (Swift/AppKit) on this Linux desktop — it
  won't run there. Use Tier 1 for web, or a separate macOS VM for native macOS UI.

---

## 3. End-to-end: both tiers in the pipeline

```
Slack: "@Puck the Login button does nothing"
   │
queue.py ─ enqueue, "you're #N in line"
   │
fixer.run_job:
   ├ worktree off main  (github_ops.prepare_worktree)
   ├ Claude Code: reproduce → root cause → minimal fix → add test   (unchanged)
   ├ tests (run_tests) + self-review loop (review_diff, ≤ review_max_rounds)
   ├ RECORD BEFORE/AFTER  ← the hidden screen lives HERE
   │     ├ base worktree off main         (prepare_base_worktree)   = BEFORE
   │     ├ fix worktree                                              = AFTER
   │     └ recorder.record_before_after(hook, base, fix):
   │           Tier 1 → Playwright headless hook  ($PUCK_RECORD_OUT)
   │           Tier 2 → POST /vd/run to the Docker desktop (computer use)
   │                    → same $PUCK_RECORD_OUT contract
   ├ PR  (commit_all → push → gh pr create)
   ├ Fix Card: upload_video(before,"Before"); upload_video(after,"After");
   │           blocks.fix_card(... needs_accept = autonomy not in {auto,workflow})
   │
Accept ─▶ ship_job: rebase_on_base → merge_pr → run_deploy → "it's live"
Reject ─▶ close_pr + cleanup_worktree
Can't fix / red tests / failed review ─▶ _escalate to next engineer with draft branch
```

The hidden screen changes **only the record step**. Everything else
(queue, fix, review, PR, accept/ship, escalation) is untouched. If a tier returns
`(None, None)` (no clip), the card honestly shows a text before/after — the
existing degrade path.

---

## 4. Components, commands, repos to fork

**Repos to fork**

- **`anthropics/anthropic-quickstarts`** → `computer-use-demo/` — the Tier 2
  container (Xvfb + Mutter + x11vnc/noVNC + xdotool/scrot + the agent loop in
  `loop.py`). Fork → strip Streamlit from the default path, add the
  `/vd/run` job server, add ffmpeg session recording. Image:
  `ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest`.

**New, in this repo (`puck/`)**

| Path | What |
|---|---|
| `tools/puck/repro.mjs` | Tier 1 Playwright hook (per target repo) |
| `puck/stages/vd_client.py` | host→container `/vd/run` client; writes `$PUCK_RECORD_OUT` |
| `puck/config.py` `RepoCfg.vd` | new optional field (Tier 2 config block) |
| `docker/puck-vd/` | the forked + slimmed computer-use container |

**Key commands**

```bash
# Tier 1
npm i -D playwright && npx playwright install chromium

# Tier 2 — build + run the hidden desktop
docker build -t puck-vd:latest docker/puck-vd
docker run -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v $HOME/.anthropic:/home/computeruse/.anthropic \
  -p 9000:9000        `# job server`               \
  -p 6080:6080        `# noVNC, ONLY when peeking`  \
  -v "$WORKTREE":/workspace:ro -it puck-vd:latest

# Peek (optional): open http://localhost:6080/vnc.html  (or :8080 combined)
# Record the framebuffer: ffmpeg -f x11grab -video_size 1024x768 -i :1 out.mp4
```

`requirements.txt` already notes Playwright as the optional video path; add it
there. The `anthropic` SDK is needed only inside the container (the loop), not on
the host.

---

## 5. Safety (carry the official precautions in)

Computer use's headline risk is **prompt injection** — the model may obey
instructions embedded in a webpage/screenshot and override the user. Anthropic now
runs classifiers that nudge the model to ask for confirmation when injection is
suspected (disable only via support — don't). For Puck:

- **Isolation is already the design.** Tier 2 runs in a dedicated container with a
  minimal-privilege user; Tier 1 runs headless Chromium with no profile. No real
  secrets mount in.
- **No sensitive credentials** in the container. Use throwaway test accounts for
  any login flow.
- **Domain allowlist** for any internet access from the container.
- **Human confirmation for consequential actions** (purchases, ToS, cookie
  walls) — which Puck already enforces structurally: the agent only ever
  *reproduces/records* in the sandbox; the *consequential* act (merge + deploy) is
  the existing **Accept** tap (`autonomy: propose` default). Keep VD jobs on
  `propose` until trusted.
- The existing worktree isolation (every fix in a throwaway checkout) and
  `--dangerously-skip-permissions` only ever touching that copy still hold.

---

## 6. Honest limits

- **Latency.** Anthropic explicitly flags computer use as **too slow for real-time
  human-in-the-loop** — every step is a full model round-trip + screenshot
  encode/decode + action settle. Tier 2 verification takes **many seconds per
  step**, minutes per scenario. That's why Tier 1 (deterministic, no model in the
  loop) handles the common web case, and Tier 2 is for background "reproduce this
  unknown thing," not snappy interaction.
- **Apple Silicon emulation.** The x86 container runs emulated on M-series Macs —
  slower still. Acceptable for background record/verify; not for anything
  interactive.
- **Cost scales with screenshots** (~1k–1.8k tokens each, one+ per turn) — long VD
  sessions add up. Caching + screenshot pruning are mandatory, not optional.
- **Computer use is still BETA** as of mid-2026 — not GA, needs the beta header,
  no official GA date (Q4 2026 is third-party speculation). Pin the header/model
  pair and treat the surface as movable.
- **The controlled screen is virtual, never the Mac.** Tier 1 = headless Chromium;
  Tier 2 = the container's Linux X11 display. **Invisibly controlling the real
  macOS GUI is not possible on one local Mac** — it needs a separate machine or a
  headless macOS VM. Mac-native (Swift/AppKit) apps can't be tested on the Linux
  desktop at all.
- **Tier 1 only does what its script says** — it can't improvise on an unknown UI.
  **Tier 2 can improvise but is slow, costly, and Linux-only.** Pick per bug; both
  hand back the same `(before_video, after_video)` so the Fix Card never knows
  which produced the clip.
```
