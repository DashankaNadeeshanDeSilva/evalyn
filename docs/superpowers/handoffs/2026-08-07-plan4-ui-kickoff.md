# Plan #4 (`evalyn ui`) — session handoff & kickoff

**Written:** 2026-08-07, immediately after Plan #3 merged. **Branch:** start from `dev` @ `4717891`.
**Nothing about Plan #4 is decided yet — this session's first job is to decide it, with the maintainer.**

---

## 1. Where things stand

**Plan #3 (`discover` + the flywheel) is COMPLETE and MERGED** — PR #7 → `dev` @ `4717891`, released as
**v0.4.0**. All three modes now ship: `gate`, `compare`, `discover`.

Verified at merge: **726 tests passing** warning-clean (and warning-clean under `FORCE_COLOR=1`, which CI
forces), `ruff` clean, both packs `validate-pack` exit 0.

**What `discover` does**, since the UI has to render it: an agent adaptively probes a target through a
closed action enum (`send`/`propose`/`stop`, no URL/file/shell tool); **the real tier-1/tier-3 scorers
decide** whether a candidate weakness is confirmed — the agent never self-certifies, and *unsure is never
a finding*; confirmed findings are emitted as outcome-graded probe YAML into an **inert staging
directory** (`<pack>/discoveries/`, which `gate` does not load), replayed once to record reproducibility,
and then **a human reviews and hand-adopts** them into `<pack>/probes/`.

**It works on a real product.** A consented live run against TwinCore (2026-08-06, ~$0.27 billed) returned
**2 confirmed findings, both replay-reproduced**: a safety-critical PII leak (the twin volunteers its
owner's email — and, per the follow-up report, phone number — to an anonymous visitor) and a groundedness
failure. Those artifacts are the demo's pre-baked TwinCore material.

## 2. The goal, and the deadline

**Build the `evalyn ui` cockpit — a local UI for watching runs, browsing results, and showing `discover`
findings.** The AI Tinkerers Bremen demo is **2026-08-14** (7 days out), and the committed demo proposal
(`docs/2026-08-14-ai-tinkerers-demo-proposal.md`) promises a local `evalyn ui` cockpit. It is the one
thing the proposal commits to that does not exist.

**Fallback, already agreed:** if the UI does not land in time, the demo falls back to the **toy flywheel**,
which runs entirely from the terminal and needs no UI. That fallback is proven and green today, so the UI
is upside, not a single point of failure. Do not let UI work put the fallback at risk.

## 3. The four existing Plan #4 docs — and why they cannot be executed as written

```
docs/superpowers/plans/2026-07-24-evalyn-pro-4a-simulation.md       8 tasks, 577 lines
docs/superpowers/plans/2026-07-24-evalyn-pro-4b-judging-trust.md    8 tasks, 291 lines
docs/superpowers/plans/2026-07-24-evalyn-pro-4c-targets-reporting.md 7 tasks, 213 lines
docs/superpowers/plans/2026-07-24-evalyn-pro-4d-ui.md               9 tasks, 330 lines
docs/superpowers/specs/2026-07-24-evalyn-pro-design.md              (the umbrella spec)
docs/superpowers/specs/2026-07-24-evalyn-pro-ui-design.md           (the UI spec 4d builds to)
```

**Read them — they contain a lot of good thinking and should be mined, not discarded.** But four facts
about them are settled and should not be re-derived:

1. **They all predate the code they build on.** Written 2026-07-24 — before Plan #2b *and* Plan #3
   shipped. 4d's Task 0 exists precisely to re-baseline; 4a–4c need the same.
2. **4d has hard dependencies on unbuilt work.** Its Task 0 reads `src/evalyn/review/` (#4b queue /
   label / promote) and assumes a post-#4c run layout (`manifest.json`, `verdicts.jsonl`,
   `review_queue.jsonl`, `labels.jsonl`, `report.html`). **None of that exists.** Its Tasks 5 and 7
   (review, trends, judge-trust pages) depend on 4b outright.
3. **4d contains zero mentions of `discover`** — it was written before Plan #3 existed, so it has no
   surface for the findings the demo needs to show. The maintainer has confirmed a **findings view is
   demo-critical**. (Precedent for amending: 4d already carries a 2026-07-28 amendment for Plan #2b's
   cost meter + compare scoreboard.)
4. **Sequential 4a→4d is not feasible by 2026-08-14.** 32 tasks / 1,411 spec lines versus Plan #3's
   15 tasks / 305 lines, which took 4 calendar days and 42 commits. That is ~4.6× the specified work in
   less time — before counting an entirely new frontend toolchain (Node 22, Vite, React 18, TS, Tailwind,
   shadcn subset, TanStack Query, React Router, Recharts, Vitest, Playwright, plus building the SPA into
   `src/evalyn/ui/static` and packaging it in the wheel) whose first-contact costs are lumpy.
   **The structural problem is worse than the volume: 4d is last in the chain, so the only demo-critical
   piece arrives last.** Any slip anywhere means demo day with no UI at all.

## 4. The maintainer's stated direction (starting point, not a decision)

> *"I am leaning towards build the demo-critical slice first, + cherry pick some nice and cool features
> from 4a, 4b and 4c which create values and include. Anyway lets clearly discuss this in the new session."*

So: **a demo-first UI slice, re-baselined against post-Plan#3 code, plus selectively cherry-picked
high-value features from 4a/4b/4c.** The maintainer explicitly wants this **discussed and decided in
session**, not assumed. Your job is to run that discussion well, then write the plan.

Two inputs for it:
- **Demo-critical, already confirmed:** a `discover` findings view (read-only: objective, confirmed,
  replay verdict, provenance, the staged probe). Read-only keeps it small — no launch/control plumbing.
- **First thing to defer, regardless:** **4a (simulation)** is the largest single plan and has nothing to
  do with the demo.

Open questions worth putting to the maintainer, with a recommendation each:
- Which 4b/4c features genuinely earn their place in the slice? (Judge-trust trends are attractive but sit
  on unbuilt 4b machinery; run-directory layout from 4c may be needed regardless.)
- Live streaming of an in-progress `gate` run (SSE + event emitter) versus read-only browsing of finished
  runs — the former is the better demo but is most of 4d Tasks 1–4.
- Does the UI need `compare` surfaces for the demo, or gate + discover only?
- Ship as the `evalyn[ui]` extra as 4d designs, or keep it simpler for now?

## 5. How to work this session

1. **`superpowers:brainstorming` FIRST.** Do not jump to a plan or to code. Read the four plans and both
   specs, form a view, and work the scope question through with the maintainer.
2. **Then plan mode** (`EnterPlanMode` → `ExitPlanMode` for approval), and
   **`superpowers:writing-plans`** to produce the executable task-by-task plan, in
   `docs/superpowers/plans/`, matching the house style of
   `docs/superpowers/plans/2026-08-04-evalyn-plan3-discover.md` (Global Constraints block at the top,
   numbered tasks with Files / Interfaces / checkbox steps, an Acceptance section).
3. **Then execute** with `superpowers:subagent-driven-development` — fresh subagent per task, controller
   rulings written to a FILE before each dispatch, TDD with a **discriminating** RED (a bare
   `ImportError` is not evidence; this project has required an inverted-stub/mutation demonstration every
   task), two-stage review (task review → fix rounds → scoped re-review).

## 6. Working agreements (non-negotiable — carried from Plan #3)

- **Models:** controller session on Fable 5; **all subagents on Opus 5** — set `model: opus` explicitly on
  **every** dispatch (implementers, fixers AND reviewers). An omitted model silently inherits the
  session's.
- **Delegate all implementation to subagents.** The controller orchestrates, reviews and verifies. This is
  also context hygiene: subagents burn the big reads in their own context and return conclusions.
- **Branch:** cut a feature branch from `dev` (`dev` @ `4717891`); PR back to `dev`. Never commit code
  straight to `main`. **Documentation-ONLY changes commit directly on `dev`** (2026-07-23 exception).
- **Commits happen automatically** under the maintainer identity, no Claude trailer:
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit …`
  Conventional prefixes. Stage files **explicitly — never `git add .`** (an untracked `.claude/` must stay
  untracked). **ASK before every push and before opening/updating any PR.**
- **`uv` only** — system `python3` is 3.9 and cannot run Inspect. Suite stays green and warning-clean:
  `uv run pytest -q -W error::RuntimeWarning` (**726** at branch start) and `uv run ruff check src/ tests/`.
- **CI forces colour.** A test asserting substrings against Typer/Click `CliRunner` output must import
  `CliRunner` from `tests/cli_runner.py` (ANSI-stripping), **not** from `typer.testing` — otherwise Rich's
  escape sequences break the match in CI while passing locally. Verify new work with
  `FORCE_COLOR=1 uv run pytest -q -W error::RuntimeWarning` too.
- **CI runner starvation is a known false red:** jobs have twice been cancelled with `steps=0` after
  exactly 15 minutes because no runner was assigned. Before treating a CI failure as real, check
  `gh run view <id> --json jobs` for `steps=0`; if so, `gh run rerun <id> --failed`.
- **Never** overwrite `packs/twincore/calibration.json` outside a consented passing calibrate run. Never
  commit `runs/`. The NiuwnAI product repo is READ-ONLY.
- **Verification before completion:** run the tests/lint and show real output before claiming done.

## 7. Inherited open items — read before planning

`docs/JOURNAL.md` → **Plan #3** → *Open items — deferred findings register*. It was triaged at Plan #3's
final review; everything left is explicitly deferred to Plan #4 or later. Ones that touch UI work:

- **Run-directory layout** — 4c assumes files that do not exist. Whatever the UI reads, the layout must be
  settled first (this is 4d Task 0's real content).
- **A shared `_run_pack_eval` extraction** (register row 20a) — a gate-spine refactor, correctly parked as
  wanting its own review.
- **Something writes into the repo's gitignored `logs/`** during the suite — harmless, but it means a
  clean `git status --porcelain` cannot prove "the suite wrote nothing".
- **`--i-know-this-is-prod` is documented but NOT implemented** (`README.md`, `docs/CONTEXT.md`, both
  design docs). Today the target allowlist is the only barrier to pointing a run at production. If the UI
  can launch runs, this matters more, not less.
- **The `injection` objective's confirmation** was fixed in the PR #7 review round (the agent-quoted slot
  is now `weight=1.0`, matching `_pii_checks`), so the earlier "self-confirming" caveat is **closed** —
  do not re-raise it from stale notes.

## 8. Demo material and a live PII hazard  ⚠️

Two confirmed TwinCore findings sit **unadopted** in `packs/twincore/discoveries/` (gitignored). They are
the demo's pre-baked material and the natural content for the UI's findings view.

**Do NOT adopt the PII finding by moving it into `packs/twincore/probes/`.** That file embeds the owner's
real email verbatim as a check value — it must, or the probe stops being outcome-graded — and `probes/` is
**tracked** in a **public** repo. The staging dir is gitignored precisely to prevent this; moving the file
is what removes the guard. If a gate probe for this is wanted, hand-write one asserting the *violation
class* (the `no-pii-leak` invariant) without pinning the real address — exactly what `_persona_checks`
does deliberately. The hallucination finding pins no personal data and is safe to adopt.

A bug report for the NiuwnAI team exists at
`/Users/dashankadesilva/Drive/Projects/niuwnai-twincore-pii-leak-2026-08-07.md` — **outside this repo, on
purpose**, because it contains a real email address. Do not copy it in.

## 9. Orientation docs

- `docs/CONTEXT.md` — orientation, locked decisions, working preferences. **Read first.**
- `docs/2026-07-21-evalyn-design.md` — the full technical design.
- `docs/ROADMAP.md` — how the plans stage; Plan #3 now ✅ built (v0.4.0).
- `docs/JOURNAL.md` — progress journal, per-task history, the deferred register.
- `docs/EVALYN_EXPLAINED.md` — plain-English overview (corrected in Plan #3: adoption is human-gated).
- `docs/2026-08-14-ai-tinkerers-demo-proposal.md` — what the demo promises. **Note:** it still describes
  the `evalyn ui` cockpit and "auto-emitting" probes; the maintainer ruled on 2026-08-06 that it stays as
  **forward-looking intent** and is not to be edited. Re-read it once Plan #4's scope is known.

## 10. Pending housekeeping (maintainer's call, not urgent)

- Delete the merged `feat/plan3-discover` branch (local + remote)? Fully merged, safe.
- Delete the Plan #3 SDD workspace `.superpowers/sdd/2026-08-04-evalyn-plan3-discover/`? The protocol says
  remove it once merged — but it holds `twincore-discover.stdout`, the live-run capture and demo material.
  Suggest keeping that one file.

---

## Kickoff prompt for the new session

```
We're starting Plan #4 — the `evalyn ui` cockpit. Plan #3 (`discover`) is complete and merged to `dev`
@ 4717891 (v0.4.0, 726 tests green). Start from `dev`.

Read first, in this order:
1. docs/superpowers/handoffs/2026-08-07-plan4-ui-kickoff.md  — full state transfer (start here)
2. docs/superpowers/plans/2026-07-24-evalyn-pro-4{a,b,c,d}-*.md — the four existing Plan #4 docs
3. docs/superpowers/specs/2026-07-24-evalyn-pro-ui-design.md + evalyn-pro-design.md — the UI/umbrella specs
4. docs/JOURNAL.md → Plan #3 → "Open items" — the deferred register you inherit
5. docs/2026-08-14-ai-tinkerers-demo-proposal.md — what the demo promises

DO NOT start coding or writing a plan. The scope is genuinely undecided and I want to decide it with you.

The four Plan #4 docs cannot be executed as written: they predate Plan #2b and #3; 4d depends on unbuilt
4b/4c machinery; 4d has zero mentions of `discover`; and sequential 4a→4d is ~4.6x Plan #3's specified
work in less time, with the only demo-critical piece (the UI) last in the chain. The handoff §3 has the
numbers.

My leaning: build the demo-critical slice first, re-baselined against post-Plan#3 code, and cherry-pick
the genuinely valuable features from 4a/4b/4c into it. A read-only `discover` findings view IS
demo-critical. 4a (simulation) is the first thing to defer. But I want this discussed properly, not
assumed — bring me options and a recommendation.

Use superpowers:brainstorming FIRST to work the scope question through with me. Then plan mode, then
superpowers:writing-plans for the executable plan, then subagent-driven-development to execute.

Working agreements: controller session stays on Fable 5, ALL subagents on Opus 5 (`model: opus` set
explicitly on every dispatch — implementers, fixers AND reviewers); delegate all implementation; feature
branch off `dev`, PR back to `dev`; commits automatic under the maintainer identity with no Claude
trailer, staged explicitly (never `git add .`); ASK before every push and any PR; `uv` only; suite stays
green and warning-clean in BOTH colour modes (CI forces colour — see handoff §6). Controller rulings to a
FILE before each dispatch; TDD with a DISCRIMINATING red.

Deadline context: AI Tinkerers Bremen demo is 2026-08-14. The toy-flywheel fallback needs no UI and is
green today — the UI is upside, so don't put the fallback at risk. Think hard. Use skills. Ask me
questions.
```
