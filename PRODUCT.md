# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary and only confirmed user: the maintainer, on their own machine.** A single person running
LLM evaluations locally and inspecting the results. There is no multi-user model, no authentication,
no sharing, and no team workflow.

This has a direct design consequence: optimise for **density, keyboard speed, and expert
affordances** over onboarding. The user already knows what a probe, a pack, `pass^k`, a gate verdict
and judge trust are — the interface does not need to teach them.

Evalyn itself is a public MIT project, so engineers adopting it into their own CI are a plausible
future audience. **That audience is not confirmed and must not be designed for speculatively.**

## Product Purpose

Evalyn is a standalone, project-agnostic **evaluation agent for LLM-powered products**, built on
Inspect AI, with three modes: `gate` (block a release on regressions), `compare` (weigh two
candidates), and `discover` (hunt for unknown failures and emit new regression probes).

The cockpit is the **local web surface over that engine**. Its database is the `runs/` directory —
it reads run artifacts written by the CLI and presents them as history, verdicts, transcripts,
findings and trends.

Success is that the maintainer can answer "did this change break anything, and what exactly did the
model say when it broke?" without reading raw JSON.

## Positioning

**Enforcement, not advice.** Evalyn's mechanism is a gate that fails a build, not a dashboard that
reports a score. The parts a neighbouring eval tool could not truthfully copy:

- **Per-probe pass/fail policy lives in Evalyn's own gate-diff layer**, not in the underlying
  harness — safety-critical probes gate on **`pass^k`** (every trial must pass), not on an average.
- **The judge is a different model family from the generator by default**, to avoid self-preference
  bias, and judge trust is measured and reported rather than assumed.
- **A run refuses any target `base_url` not allowlisted in the pack.**
- **`discover` closes the loop** by emitting new regression probes back into the pack, so found
  failures become permanent gates.

## Operating Context

- Runs locally; the user starts it themselves and it serves `127.0.0.1`.
- **`runs/` is the database.** It is gitignored, so nothing the cockpit indexes is committed.
- The product is **terminal-first by heritage** — the CLI is the mature, proven surface and remains
  fully usable without the cockpit. The cockpit is additive and must never be required.
- Committed baselines live at `ci/baseline-<pack>.json` by convention; the CLI's `--baseline` default
  (`runs/baseline.json`) is pack-agnostic and therefore cannot be committed.
- Evaluation runs cost real money (judge model calls plus the target product's own inference), and
  packs carry explicit budget caps.

## Capabilities and Constraints

**The cockpit is a control surface, not only a viewer.** It launches runs and can pause and cancel
them. That is durable product truth, not demo scope, and it means the interface carries genuinely
destructive and genuinely expensive actions.

Confirmed constraints that shape the UI:

- **Degradation, not failure.** A hostile `runs/` directory — truncated JSON, legacy artifacts,
  wrong permissions — must produce degraded rows that still carry a real `run_id`, never an
  exception that empties the listing.
- **Redaction is a chokepoint**, not a per-view concern: transcripts and findings can contain real
  identifiers from the product under test.
- **Pause does not stop spend.** Pausing starts no new samples, but in-flight trials finish and
  continue to bill. Any control affordance must say so honestly rather than implying a hard stop.
- **One run at a time per `runs/` directory.**
- `pass^k` semantics must not be weakened for convenience: lowering `k` collapses the guarantee and
  makes a guardrail that fails one time in three appear green.
- Terminology is fixed and used as-is: probe, pack, trial, gate, verdict, `pass^k`, baseline,
  judge trust, discovery, finding.

## Brand Commitments

- Name: **Evalyn**. Public repository, MIT licensed.
- The README is deliberately aspirational about shipped capability; that is a maintainer decision,
  not an error to correct.

## Evidence on Hand

Real material the interface can be designed against:

- **~80 indexable run artifacts** in `runs/` (81 JSON files minus `baseline.json`, which the run-id
  grammar excludes). This is live data, not fixtures, and the count changes whenever an eval runs —
  **it must never be hardcoded**.
- A real field test against a shipped product (referred to as twincore), including a genuine
  guardrail failure: `injection-exfil-boundaries` at `pass^k = 0.0`.
- A committed example baseline at `ci/baseline-example.json`.
- A four-artifact UI fixture corpus at `tests/fixtures/ui_runs/`, verified to contain no real
  identifiers.

**Absences that future work must not fabricate:**

- **There are zero `compare` artifacts in `runs/`.** Any compare view will render an empty state
  against real data. Do not invent compare data to fill it.
- **There is no committed twincore baseline.** `runs/baseline.json` exists but is a pre-Plan-#2a
  artifact that fails to load.
- **`packs/example/discoveries/` contains only `.gitkeep`** — the discover fixture's `probe_path`
  points at a directory with no findings in it.

## Product Principles

1. **The terminal path must never be put at risk by the cockpit.** The CLI is the proven surface;
   UI work that touches engine code must prove existing behaviour is unchanged.
2. **Show the evidence, not just the verdict.** A red gate is only useful if the user can see what
   the model actually said. The transcript is the payload, not a detail view.
3. **Degrade visibly rather than hide.** A run that cannot be read is shown as unreadable with its
   id intact — never silently omitted from the list.
4. **Be honest about cost and irreversibility.** Actions that spend money or interrupt work say so
   plainly, including the fact that pausing does not stop billing.
5. **Density over decoration.** The user is an expert reading dense output; whitespace and ornament
   must earn their place against information.

## Accessibility & Inclusion

**Committed standard: WCAG 2.1 AA.**

- Body text ≥ 4.5:1 contrast; large text ≥ 3:1.
- Visible focus states; fully keyboard navigable.
- **Never colour alone for meaning.** This is load-bearing rather than decorative here: the product's
  central output is a pass/fail verdict, and red/green is the most common colourblind failure pair.
  Verdict state must always carry a shape, icon, or word alongside its colour.
