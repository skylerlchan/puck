# The Fix Card — AI PR artifact for fast merge

*Created 2026-06-04. Internal product spec, draft for refinement.*

## What this is

The AI doesn't just open a PR — it produces a **Fix Card**: a structured proof-of-fix that
replaces the wall-of-text PR description and drives a redesigned merge UX. The card answers the
only question a reviewer has:

> **"Has the baseline moved toward what I asked for, and is it safe to merge?"**

Everything is ordered by **decision priority**, not by chronology. You can merge after reading
the top two sections; the rest is progressive disclosure for when you want it.

---

## Structure (top → bottom = most → least important)

### 1. Verdict — the one-line TL;DR
- One sentence: what was broken → what's now true.
- A **status chip**: `Verified ✓` (reproduced + fixed + tests green) · `Needs your eyes` (couldn't auto-verify) · `Failed`.
- This alone tells you whether to merge or scroll.

### 2. Before → After — the proof (the heart)
Three states, side by side. This *is* "show the baseline improved toward what I want":

| Target (what I asked for) | Before (baseline / failing) | After (fixed) |
|---|---|---|
| The expected behavior, from your drop-in | The failing state — your screenshot, or the agent's reproduction | The agent's captured result post-fix |

Rendered by bug type:
- **Visual bug** → before/after screenshots (side-by-side or slider).
- **Behavioral bug** → `before: returns X (wrong)` → `after: returns Y (correct)`.
- **Metric bug** (perf/quality) → `before: 850ms` → `after: 120ms`, with the **target marked** so the move toward goal is visible.

The reviewer should *see* the delta in one glance, not infer it.

### 3. How it was reproduced — proof the bug was real
- 2–4 steps the agent took to trigger the bug.
- Root-cause trigger in one line.
- **Failing proof**: the test/capture that was red *before* the fix.
- This proves the agent fixed the *actual* problem, not a guess.

### 4. How it was fixed — proof the fix is right
- Root cause (1 line) → approach (1 line).
- Files touched (count + names) = blast radius.
- The diff — **collapsed by default** ("I don't even need to know" unless I want to).
- The new/updated test that locks the fix in.

### 5. Safety panel — drives the merge button state
- Tests: `142 passed / 1 added`, suite green/red.
- Scope: N files, M lines.
- Risk flags: `auth` · `migration` · `public-api` · `none`.
- Open questions the agent had (or "none — fully autonomous").

### 6. Actions — the redesigned buttons
Button prominence is **computed from §5**, not always-on:

| Condition | Primary button | Others |
|---|---|---|
| Verified + green + no risk flags | **Merge** (one tap) | Ask · Reject |
| Verified + risk flags | **Merge** (requires expanding §2 first) | Merge behind flag · Ask · Reject |
| Needs review / suite red | **Ask** / **Reject** | Merge (muted) |

- **Ask a question** re-triggers the agent in-thread (clarify → it revises the card).
- **Reject** captures a reason → fed back to the agent.

---

## Data schema (buildable shape)

```json
{
  "verdict": {
    "summary": "Login button did nothing on mobile Safari — now submits correctly.",
    "status": "verified",                // verified | needs_review | failed
    "confidence": 0.9
  },
  "target":  { "description": "Tapping Login should submit the form",
               "source": "slack", "evidence": ["expected.png"] },
  "before":  { "description": "Tap does nothing; no network request fires",
               "evidence": {"type":"screenshot","ref":"before.png"}, "metric": null },
  "after":   { "description": "Tap submits; redirects to dashboard",
               "evidence": {"type":"screenshot","ref":"after.png"},  "metric": null },
  "repro":   { "steps": ["Open /login on iOS Safari","Tap Login","No submit"],
               "rootCauseTrigger": "overlay swallowed the tap",
               "failingProof": "login.mobile.spec.ts ❌ (before)" },
  "fix":     { "rootCause": "z-index overlay intercepted the tap",
               "approach": "Lowered overlay z-index + pointer-events:none",
               "filesChanged": ["LoginForm.tsx","overlay.css"],
               "diffRef": "pr/123/files", "testAdded": "login.mobile.spec.ts ✅ (after)" },
  "safety":  { "testsPassed": 142, "testsAdded": 1, "suiteStatus": "green",
               "linesChanged": 18, "riskFlags": [], "openQuestions": [] },
  "actions": { "primary": "merge", "available": ["merge","merge_watch","ask","reject"] }
}
```

The card UI is a pure render of this object. The agent's job ends at producing a valid `FixCard`;
the merge UI is a deterministic function of it.

---

## The one principle

**Merge decision = read §1 + §2 + press §6.** Sections 3–5 exist only for when trust isn't
automatic. Optimize the card so the common case (verified, low-risk) is a single tap, and the
risky case forces exactly the right glance — nothing more.

## Open refinement questions
- Metric bugs: do we always require a target value to show "movement toward goal," or allow "fixed/not-fixed" binary?
- Does "Ask" thread back into the *same* card (revise in place) or spawn a new revision (v2 card)?
- Risk flags: hardcoded set, or repo-configurable (CODEOWNERS-style)?
