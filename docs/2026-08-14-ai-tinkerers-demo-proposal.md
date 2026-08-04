# AI Tinkerers Bremen — Demo Proposal (Fri, Aug 14, 6PM CEST)

Copy-paste-ready answers for the submission form at
https://bremen.aitinkerers.org/meetup/mu_2qFDcsvx_Q0/speaking

---

## Talk Title

**Evalyn: Red-Teaming Conversational AI in CI**

*(alternatives, matched to AI Tinkerers title conventions:)*
- Evalyn: LLM Judges That Refuse to Run
- Evalyn: CI-Grade Evals for Conversational AI

---

## What did you build? (Required)

Evalyn is an open-source evaluation engine that black-box-drives any conversational AI product over its real HTTP/SSE chat API, grades every reply through a three-tier trust ladder — deterministic checks, an evidence-quoting classifier judge, and a human-calibrated rubric judge — and returns a CI-grade PASS/FAIL against a committed baseline. It runs in three modes — `gate` (did I break anything?), `compare` (blind A/B of two configs), and `discover` (a red-team agent whose confirmed findings become new regression probes) with a local `evalyn ui` cockpit for watching runs, diffs, and judge-trust trends. Sessions can be scripted or driven by persona-based LLM-simulated users with seeded perturbations — typos, topic drift, mid-conversation goal shifts. The engine knows nothing about any specific product: everything product-specific lives in a swappable YAML "target pack." I built it because my own shipping product — NiuwnAI, a digital-AI-twin app had zero evals.

Live, I'll run a short but real showcase against the actual NiuwnAI endpoint: a focused
`evalyn gate` pass streaming injection-probe verdicts in the terminal, ending with a
deliberately regressed prompt turning the baseline diff red. The rest — the calibration gate
that refuses to run below 85% human agreement, `discover` auto-emitting new regression probes,
the `evalyn ui` cockpit — I'll show from real logs and the repo as time allows.

---

## What will another builder learn? (Required)

**The reusable pattern: strict engine/pack separation.** The engine contains zero NiuwnAI
knowledge — endpoints, probes, rubrics, anchors, budget, and allowlist all live in a YAML
target pack. Evaluating *your* conversational AI means writing a pack, not eval code: the same
pattern took NiuwnAI from zero evals to a CI-gated 50-probe suite with an enforced calibration
gate, and it ports to any HTTP/SSE chat backend (only the probes and rubrics stay bespoke).

Two hard-won lessons along the way:

1. **pass@k lies for safety probes — gate on pass^k.** A jailbreak that passes 2 of 3 trials
   looks "mostly fine" on average, but the one time it leaks, a real user gets the leak.
   Averaging metrics hide exactly the failures that matter most.

2. **Everyone preaches "grade the grader" — no tool actually makes you.** What changed my
   results was enforcement, not advice: every rubric must individually clear 85% agreement
   with 44 hand-labeled anchors (11 per rubric) — a weak rubric can't hide behind a strong average — or the
   judge refuses to run; verdicts are discarded unless the judge quotes its evidence verbatim;
   and the judge never shares a model family with the generator.

---

## Technologies Used (Required)

- **Inspect AI ≥0.3.249 (UK AI Safety Institute)** — the eval spine: probes compile to
  Task/Solver/Scorer with pass@k / pass^k reducers; the gate re-reads its immutable eval logs
  for the PASS/FAIL call.
- **httpx (async)** — session driver streaming the target's real chat API via a four-dialect
  SSE parser (Vercel AI SDK, raw SSE, named SSE, JSON).
- **Claude Sonnet (Anthropic API)** — Tier-3 G-Eval rubric judge: k=3 draws with median
  voting, abstains on disagreement, calibrated against 44 human-labeled anchors (11 per rubric).
- **OpenAI API** — the generator family under test; judge ≠ generator separation warned on by
  default, hard-enforced for ≥2-family judge panels certified via Cohen's κ.
- **Pydantic v2 + YAML** — the target-pack contract: probes, rubrics, anchors, URL allowlist,
  per-run USD budget ceiling.
- **Typer** — CLI (`gate / compare / discover / calibrate / validate-pack`); exit codes
  0 pass / 1 fail / 2 setup error / 3 run-invalid (errored ≠ failed).
- **FastAPI + React (Vite, TypeScript, Tailwind, Recharts)** — the `evalyn ui` local cockpit:
  prebuilt bundle shipped in the wheel, `runs/` as its database.
- **GitHub Actions** — reusable `evalyn-gate.yml` workflow: gates every PR, posts the report
  as a PR comment.
- **NiuwnAI** — my shipping digital-AI-twin chat product: live demo target and reference
  pack; a zero-key `mockllm` mode + practice target let anyone try it without API keys.

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
  not the video of the thing running"). New pacing per the reduced live scope: ~2 min live
  (focused gate pass on the injection subset, pre-warmed, ending on the red baseline diff) +
  ~3 min explanation; keep calibrate / `discover` / `evalyn ui` as pre-baked logs and
  screenshots to click into if time allows.
- **Don't open with "I built an eval framework"** — 30+ exist and the audience is fatigued.
  Open with the product that had zero tests, or the tool that refuses to run for its own
  operator. Let "framework" be incidental.
- **Q&A ammo — "why not just promptfoo?":** promptfoo was acquired by OpenAI (March 2026), so
  the leading independent open-source option in this category is gone; and the load-bearing
  features here (calibration hard-gate, per-probe pass^k, enforced judge≠generator family,
  confirm-before-promote for red-team findings) are best-practice advice that no mainstream
  tool ships as enforcement. One sentence max — no market framing on stage.
- **Wifi fallback:** have the pre-recorded gate-run capture locally as a break-glass backup.
