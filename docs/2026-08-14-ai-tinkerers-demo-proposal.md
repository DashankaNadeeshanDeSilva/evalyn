# AI Tinkerers Bremen — Demo Proposal (Fri, Aug 14, 6PM CEST)

Copy-paste-ready answers for the submission form at
https://bremen.aitinkerers.org/meetup/mu_2qFDcsvx_Q0/speaking

---

## Talk Title

**My AI Product Had Zero Tests — So I Built an Eval Engine That Red-Teams It in CI**

*(alternatives, pick your favorite:)*
- Grading the Grader: Calibrated LLM Judges, pass^k, and a Gate That Says NO
- Evalyn: Turning "Vibes" into a CI-Grade PASS/FAIL for LLM Products

---

## What did you build? (Required)

Evalyn is an open-source evaluation engine (MIT, built on Inspect AI) that black-box-drives any
conversational AI product over its real HTTP/SSE chat API, grades every reply through a
three-tier trust ladder — deterministic checks, an evidence-quoting classifier judge, and a
human-calibrated rubric judge — and returns a CI-grade PASS/FAIL against a committed baseline.
It runs in three modes — `gate` (did I break anything?), `compare` (blind A/B of two configs),
and `discover` (a red-team agent whose confirmed findings become new regression probes) — with
a local `evalyn ui` cockpit for watching runs, diffs, and judge-trust trends. The engine knows
nothing about any specific product: everything product-specific lives in a swappable YAML
"target pack." I built it because my own shipping product — TwinCore, a digital-AI-twin chat
app — had zero evals.

Live, I'll run the full loop against the real TwinCore endpoint: `evalyn gate` streaming a
50-probe suite (including 31 injection attacks seeded from real production failures), then a
deliberately regressed prompt turning the baseline diff red. Then the two signature moments:
`evalyn calibrate` grading the LLM judge against 20 hand-labeled human anchors — and refusing
to run below 85% agreement — and the `discover` red-team agent auto-emitting a brand-new,
reproducible regression probe from a failure it found seconds earlier, with the whole run
watchable in the `evalyn ui` cockpit. Real code, real logs, no slides.

---

## What will another builder learn? (Required)

**The reusable pattern: strict engine/pack separation.** Evalyn's engine contains zero
TwinCore knowledge — endpoints, probes, rubrics, human anchors, budget, and target allowlist
all live in a YAML target pack. That's the takeaway story: evaluating *your* conversational AI
means writing a pack for your stack, not writing eval code — the same pattern took TwinCore
from zero evals to a calibrated, CI-gated 50-probe suite, and it ports to any chat backend
that speaks HTTP/SSE.

Two hard-won lessons along the way:

1. **pass@k lies for safety probes — gate on pass^k.** A jailbreak that passes 2 of 3 trials
   looks "mostly fine" on average, but the one time it leaks, a real user gets the leak.
   Averaging metrics hide exactly the failures that matter most.

2. **Everyone preaches "grade the grader" — no tool actually makes you.** What changed my
   results was enforcement, not advice: ≥85% agreement with 20 hand-labeled anchors as a hard
   precondition (the judge refuses to run uncalibrated), verdicts discarded unless the judge
   quotes its evidence verbatim, and the judge never sharing a model family with the generator.

---

## Technologies Used (Required)

- **Inspect AI ≥0.3.249 (UK AI Safety Institute)** — the eval spine: probes compile to
  Task/Solver/Scorer with pass@k / pass^k reducers; its immutable eval logs are what the gate
  layer re-reads to make the PASS/FAIL call.
- **httpx (async)** — the session driver: streams the target's real chat API through a
  four-dialect SSE parser (Vercel AI SDK frames, raw SSE, named SSE, JSON).
- **Claude Sonnet (Anthropic API)** — Tier-3 G-Eval rubric judge: k=3 self-consistency draws
  with median voting, abstains on disagreement, calibrated against 20 human-labeled anchors.
- **OpenAI API** — the generator family under test; judge ≠ generator family separation is
  enforced in code, with judge panels spanning ≥2 model families certified via Cohen's κ.
- **Pydantic v2 + YAML** — the target-pack contract: probes, rubrics, anchors, URL allowlist,
  and a hard per-run USD budget ceiling.
- **Typer** — the CLI (`evalyn gate / compare / discover / calibrate / validate-pack`) with
  CI-meaningful exit codes (0 pass, 1 gate fail, 2 setup error); `evalyn ui` is a local cockpit
  where every action maps to a CLI-visible artifact.
- **TwinCore** — my own shipping digital-AI-twin chat product: the live demo target and
  reference pack.

---

## Optional fields

- **Project URL:** https://github.com/DashankaNadeeshanDeSilva/evalyn
- **Co-presenters:** (none)
- **Video Demo URL:** record a 2-min terminal capture of the gate run and link it — AI Tinkerers
  organizers explicitly skip thin submissions, and a working capture de-risks the review.
- **Agreement checkbox:** tick — the demo is exactly live terminal + logs + repo, no slides.

---

## Submission & presenter notes (not part of the form)

- **Complete your AI Tinkerers profile before submitting** (GitHub + social links). Their FAQ
  says organizers pass over thin submissions/profiles; this weighs as much as the proposal text.
- **Rehearse to 5 minutes.** AI Tinkerers demos run ~5 min, live only ("show the thing running,
  not the video of the thing running"). The timed run: gate ≈90s (pre-warmed, land on the tail)
  → break-it-on-purpose ≈60s → calibrate-refuses-to-run ≈90s → `discover` emits a new probe
  file ≈60s.
- **Don't open with "I built an eval framework"** — 30+ exist and the audience is fatigued.
  Open with the product that had zero tests, or the tool that refuses to run for its own
  operator. Let "framework" be incidental.
- **Q&A ammo — "why not just promptfoo?":** promptfoo was acquired by OpenAI (March 2026), so
  the leading independent open-source option in this category is gone; and the load-bearing
  features here (calibration hard-gate, per-probe pass^k, enforced judge≠generator family,
  confirm-before-promote for red-team findings) are best-practice advice that no mainstream
  tool ships as enforcement. One sentence max — no market framing on stage.
- **Wifi fallback:** have the pre-recorded gate-run capture locally as a break-glass backup.
