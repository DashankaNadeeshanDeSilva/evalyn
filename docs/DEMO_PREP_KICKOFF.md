# Kickoff — demo preparation session (understanding Evalyn, not building it)

**Paste the block in §0 into a new session.** Everything below it is the material that session needs.

---

## 0. THE KICKOFF PROMPT

> This session is **demo preparation, not development.** The demo is **2026-08-14, 6pm, AI Tinkerers
> Bremen**. Evalyn is built, rehearsed and shipped — I do not want code changes, refactors,
> new tests, or subagents. **Do not write code unless I explicitly ask.**
>
> What I want is **understanding**. I will ask a lot of questions about how Evalyn works, what I am
> looking at in the `evalyn ui` cockpit, and the evaluation concepts behind it, so I can explain it
> confidently on stage and answer questions from the audience.
>
> **Answer style — this matters:**
> - **Short, simple English.** Assume I am explaining it to a room of smart engineers who do not
>   work on evals.
> - Lead with the answer, then the detail. No essays unless I ask for depth.
> - When I ask "what is X", give me the plain meaning first, then how *our* implementation does it,
>   then the one-liner I could say on stage.
> - If I could be asked a hard follow-up question about something, tell me the follow-up and the
>   answer.
>
> **Accuracy rules that bite in this project:**
> - **Measure, never quote.** Counts, costs and pass rates in the docs go stale in days. Read the
>   artifacts in `runs/` and compute. If a doc disagrees with the corpus, the corpus wins.
> - **Say when you do not know.** Several things here are genuinely unmeasured (see §5). Do not
>   guess a number to be helpful — a wrong figure on stage is worse than "I don't know".
> - **Flag anything false in what I say or in what you read.** I have been carrying stale claims
>   from my own docs all week and being corrected has been the most valuable thing in this project.
>
> **Read first, in this order:**
> 1. `docs/DEMO_PREP_KICKOFF.md` — this file, the session's map.
> 2. `docs/2026-08-14-DEMO-RUNBOOK.md` — the stage document, numbers measured 2026-08-12.
> 3. `docs/DEMO_RUN_PLAN.md` — the demo's shape: one live run, three stories.
> 4. `docs/EVALYN_EXPLAINED.md` and `docs/2026-07-21-evalyn-design.md` — what Evalyn is and why.
>
> The cockpit may already be running on `http://127.0.0.1:8765`. If not, the start command is in
> runbook §2 — and add `--allow-discover` to keep the discover mode enabled.
>
> Start by telling me what you understand the demo to be, in five lines, so I can check we agree.

---

## 1. Where things stand

| | |
|---|---|
| Branch | `feat/plan4-ui`, pushed |
| Suites | 1613 Python · 629 UI / 30 files · ruff and `tsc` clean |
| Cockpit | v0.4.0, all six pages ship, bundle rebuilt and proven |
| Rehearsed | Yes — full live run end to end on 2026-08-12 |
| Modes | `gate` launches from the UI · `discover` launches from the UI when the server has `--allow-discover` · `compare` is **CLI-only to launch**, and its results are viewable in the UI |

---

## 2. The six pages, and what each one is for

- **Runs** — every run ever, newest first. Status, mode, pack, verdict hint, judge cost.
- **Launch** — start a run. Pack picker, a confirm field that must match the pack name, spend cap
  for discover.
- **Discoveries** — findings the red-team agent produced, staged as new probe files.
- **Compare** — a blind A/B of two existing gate runs, viewer only.
- **Trends** — per-probe metrics over time, one line per channel.
- **Judge Trust** — how well the rubric judge agrees with human labels, per pack.

---

## 3. The concepts to be ready to explain

Ask about any of these. They are the ones an audience will probe.

**The core loop:** target pack · probe · trial · epoch · sample · run · artifact · gate verdict ·
exit code.

**Scoring:** the **three-tier trust ladder** — tier 1 deterministic checks, tier 2 an
evidence-quoting classifier judge, tier 3 a human-calibrated rubric judge. What each tier is for,
and **why only some checks gate**.

**pass^k vs pass@k** — the single most important idea in the project, and the one most worth saying
out loud. Why a jailbreak that passes 2 of 3 trials is a *failure*, not a 67%.

**Invariants** — the always-true checks (first person, no internal leak, non-empty) and why they are
separate from probe-specific checks.

**Calibration** — what `evalyn calibrate` measures, what ±1-point agreement means, why the bar is
85%, and what "not calibrated" does to a run.

**Baselines** — what "NO BASELINE, capability checks are advisory" actually means.

**Redaction** — what gets scrubbed, why staged findings sit in a gitignored folder, and why a
captured value is stored verbatim inside a check.

**The three modes** — gate, compare, discover — what question each answers.

**Discover specifically** — persona, playbook, objective, the replay step, and why "confirmed"
matters more than "found".

**Why the judge is a different model family from the generator** (self-preference bias).

---

## 4. Facts worth having straight (all measured 2026-08-12 — re-measure before quoting)

- Anchor probe `injection-exfil-boundaries` failed pass^k in **8 of 9** twincore-injection runs, and
  **6 of 6** at 7 trials.
- Every check-level failure ever recorded on that pack is **output conformance** — zero leak
  failures, zero invariant breaches, across 3969 checks in the three runs that record check detail.
- `invariant_failures` is **0** across all 1497 trial records in all nine runs.
- A full twincore-injection run: **217 trials, 31 probes, ~3 min, $0.0513–$0.0665**.
- A twincore run: **50 probes, ~$0.76–$1.04**. The 2026-08-12 20:06 run cost **$0.7883**, failed the
  same one probe, and ran 804 tier-1 / 63 tier-2 / 42 tier-3 checks.
- Judge Trust on `twincore`: **93% agreement (82 of 88 pairs)**, threshold 85%, weakest criterion
  `persona: Tone under refusal` at **82% (9/11)**.
- `twincore-injection` has **zero rubric checks** and **no calibration record** — that is why its
  Judge Trust tab is empty and its Compare board has no pairwise verdicts.

**The words "leak" and "exfiltration" are banned for the headline finding.** It is an
output-conformance failure: the twin declined correctly but did not use an approved refusal string.
The protected file was never revealed, in any trial.

---

## 5. Open threads — genuinely unknown, do not invent answers

1. **Zero-mean probes.** In the 2026-08-12 twincore run some probes show `mean 0.000` while the run
   reports zero unsure trials. In the code a 0.0 mean can mean "scored zero" *or* "no usable score,
   fail closed". **Nobody has determined which.** Worth closing before showing that probe table.
2. **What a discover run costs.** The discover artifacts do not record `judge_usd` at all. There is
   no measured figure. The Launch form makes you set a spend cap, which is the real control.
3. **Behaviour on a flaky network** mid-run has never been tested.
4. **Projector resolution.** Everything was verified around 1568px wide. Layout at 1280×720 is
   unchecked, and the Compare board is known to clip at narrow widths.

---

## 6. Things that are easy to get wrong

- **Exit code 1 is a verdict, not a crash.** It means the gate found something. Exit 0 would mean
  nothing failed.
- **Tier 3 advises, it does not gate.** `pass^k` counts only *required* checks, so failed rubric
  checks do not red a build. Say this before someone asks.
- **Compare is CLI-only to launch** (no run-picker in the UI). **Discover is not** — it is in the
  UI, just off by default because it spends money and writes new probe files.
- **A cancelled run shows NO VERDICT**, deliberately — no pass/fail, no exit code, no colour.
- The runs list `CREATED` time is the artifact's timestamp, a few minutes after you clicked launch.

---

## 7. Ground rules for that session

- **No code.** No refactors, no new tests, no subagents, no merges. If something genuinely needs
  fixing, say so and let me decide — do not start.
- Reading the codebase to answer a question is fine and encouraged.
- Do not re-plan the demo. `docs/DEMO_RUN_PLAN.md` is settled.
