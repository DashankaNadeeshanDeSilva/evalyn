# Demo run plan — one live run, three stories

**For the stage commands, port check and the numbers you may state, use
`docs/2026-08-14-DEMO-RUNBOOK.md`. This file is only the shape of the demo and the caps.**

---

## The shape

| | Story | Where it comes from |
|---|---|---|
| 1 | **The gate** — does this build still hold? | **LIVE**, launched on stage |
| 2 | **The agentic red-team loop** — discover | Pre-run, shown from the Discoveries page |
| 3 | **The rubric judge, and whether to trust it** | Pre-run twincore result + Judge Trust page |

**Only story 1 is live.** Two and three are results you already have on screen.

---

## Before the day — pre-run these

Do these once, unhurried, and look at the results. If one goes badly you still have the old ones.

- [ ] **Fresh discover run** — `packs/twincore`. **Set the spend cap on the Launch form.**
      You already have a good Aug-6 run with 2 confirmed, replay-reproduced findings, so this is a
      bonus, not a dependency. If the fresh run finds nothing, show the old one.
- [ ] **twincore gate run** (the rubric story) — 50 probes, **measured cost $0.76–$1.04**.
      Run it once, look at the outcome, and plan to show *that* result.
- [ ] Confirm the Discoveries page and Judge Trust page both look right afterwards.

---

## On the day — the 5 minutes

1. **Run the port check** (runbook §1). Twenty seconds. Do not skip it.
2. **Launch the gate run** — `twincore-injection`. 217 trials, ~3 min, ~$0.07.
3. **While it runs**, tell story 2: open Discoveries, walk the confirmed findings, explain the
   red-team loop and that the replay reproduced them.
4. **Come back to the finished board** — GATE FAILED, the failing probe, and the point that a
   deterministic check found it, no LLM involved.
5. **If there's time**, story 3: the twincore result plus Judge Trust → 93% agreement, and name the
   82% weak spot yourself.

**The 3 minutes of run time is your slot for story 2.** That's the whole reason the order works.

---

## Caps — do not miss these

| Cap | Value |
|---|---|
| Live gate run | ~$0.07, ~3 min. Pack ceiling $5.00, so it uses ~1.3%. |
| twincore rubric run | **$0.76–$1.04.** Pre-run only — never live. |
| Discover run | **You type the cap on the Launch form.** It is clamped down to the pack ceiling. |
| Live segment | 5 min total. One run only. |

**Do not run twincore or discover live.** Both cost more, take longer, and their outcome is not
predictable enough to talk over.

**Prefer pause to cancel** if you need to stop something on stage.

---

## Two accuracy notes for what you say

- **Compare is the CLI-only one.** The engine does compare fine, but the cockpit has no picker for
  choosing the two runs, so you launch it from a terminal and view the board in the UI.
- **Discover is NOT CLI-only** — it is launchable in the cockpit, but off unless the server is
  started with `--allow-discover` (it is on now). The honest line is *"it's off by default, because
  it spends money and writes new probe files."*

---

## If something breaks

Fall back to `~/Desktop/evalyn-k7-RED-2026-08-11.mov`. Stories 2 and 3 need no live run at all, so
even with no network you still have two thirds of the demo.
