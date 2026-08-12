---
version: 1
slug: "ui-src"
primary_target: "ui/src"
related_targets: []
---

# Cockpit surface brief — Evalyn `evalyn ui`

Scope: the whole cockpit surface (`ui/src/**`). Visitor mode: **Operate**.
Established by impeccable `shape` + `new-work`, 2026-08-10. Direction chosen by the surface roll
(key `3632f7e5`, assigned index 7 of the grounded list), fused with the dealt challenger
`design-canon-creator-hardware-bench`. Maintainer confirmed.

DESIGN.md is deliberately NOT written yet — it is authored at finish, from the built world.

---

## 1. Job and audience

One person: the maintainer, at their own desk, on `127.0.0.1`. They already know what a probe, a
pack, `pass^k`, a gate verdict and judge trust are. They arrive to answer one of two questions:

- *"Did this change break anything, and what exactly did the model say when it broke?"*
- *"Is something running right now, and should I stop it?"*

Density and keyboard speed beat onboarding. Do not explain the domain.

Secondary, non-binding: on 2026-08-14 this is projected to a technical audience. That constrains
**contrast and scale**, never information architecture.

## 2. Outcome and proof

Two things must be legible within seconds, and they are carried by different regions rather than
fighting for one:

- **"This is a real, working system"** — carried by the live readout and by genuine density: ~80 real
  runs, real degraded rows, real history. Never simulated.
- **"It caught a real failure"** — carried by the verdict and the transcript beneath it. The
  transcript is the payload, not a detail view.

Proof on hand: ~80 indexable artifacts, a real guardrail failure (`injection-exfil-boundaries` at
`pass^k = 0.0`), real judge-trust history.

## 3. Selected direction

**THE BENCH INSTRUMENT.** The cockpit reads as a piece of desk hardware: a light instrument face
carrying legends, readouts, and exactly one dangerous control.

**World.** A pale instrument chassis in near-zero-chroma greys — *cool* neutral, explicitly NOT
cream, sand, bone-warm or parchment (that warm-neutral band is the saturated AI default and is
banned here). Dark ink legends in the existing mono stack. Rules and separators read as engraved
panel lines, thin and confident, never as card borders. **Cards are not the organising device** — the
surface is one continuous face divided by panel lines, because a bench is one object, not a pile of
tiles. Nested cards are forbidden outright.

**The one inset window.** A single darker, recessed readout region carries LIVE state. This is the
asymmetry that breaks the strict grid, the only dark field on the page, and the reason the metaphor
survives a light theme. It appears only when something is actually running or has just finished;
it is not a permanent decorative slab.

**Safety orange is rationed to danger.** Reserved exclusively for actions that **spend money or
interrupt work** — launch, cancel. Nothing else in the interface may use it. Orange renders as a
filled key with near-black ink on top (white-on-orange typically fails AA). One primary dangerous
action per screen, always.

**Signature interaction — detents.** Controls behave like knurled hardware: filters, ranges and
toggles snap to discrete positions with a short, confident transition. No fuzzy intermediate states,
no springy overshoot. This is a UX win, not only a flourish: discrete state is what an operator can
predict, and it maps exactly to a domain whose values are enumerated (`RunStatus`, `VerdictTier`,
mode).

**Degraded rows as dead channels.** An unreadable artifact is not hidden and not styled as an error
alert. It reads like a dead channel on an instrument: the row is present, the `run_id` is legible,
the readout region is struck through or flat-lined, and the reason is stated. This is on-metaphor and
it discharges Product Principle 3 (degrade visibly rather than hide).

**Honest risk.** The metaphor can tip into skeuomorphic pastiche — knurling textures, faux screws,
bevels, glass glare. That would violate Operate mode ("expression may never obscure the task"). The
rule: the bench supplies **vocabulary and hierarchy**, never texture. No bevels, no drop-shadow
depth, no simulated materials. If a treatment exists only to look like hardware, it is cut.

## 4. Scope and boundaries

Applies to every cockpit page: runs table, gate detail, discoveries, compare, trends, judge trust.

**Untouched:** the frozen API contract (`src/evalyn/ui/models.py`), the `types.ts` mirror and its
drift guard, the toolchain pins, and the committed bundle's byte-identical property.

**Inherited, not replaced:** the status palette already keyed to `RunStatus` enum members
(`bg-status-gate_failed`, etc.) so a component cannot drift from the enum, and the `degraded` grey.
Expand this vocabulary; do not rename or re-hue it.

**Anti-goals:** no marketing hero, no metric tiles in a row of identical cards, no gradient text, no
glassmorphism, no side-stripe accent borders, no uppercase tracked eyebrow above every section, no
numbered section markers. No onboarding tour. No empty-state illustration.

## 5. States and ranges

Real ranges the layout must hold without breaking:

- Runs list: **0 to ~80+**, growing. Never hardcode a count anywhere.
- Probes per run: up to ~50; injection subset 31.
- Trials per probe: `k = 3` typically.
- Transcript turns: up to ~12 per session; text can be long and must wrap, not truncate.
- `pass^k`: 0.0–1.0. **Tabular figures required** for all numerics (pass^k, cost, duration) so columns
  don't jitter between renders.
- Cost: sub-dollar, rendered to **four decimals** — `formatUsd` in `ui/src/format.ts` returns
  `` `$${value.toFixed(4)}` `` and a named test pins it. The precision is load-bearing: a judge run
  costing a fraction of a cent must not round to `$0.00` and read as free.

Material states: first-run with an empty `runs/`; **degraded rows (common, ~26 of 80 today)**; a run
in progress; a paused run (which is still billing — the label must say so); a cancelled run; an
unreadable artifact; a compare view with **genuinely zero data** (real absence — do not fabricate);
a discoveries view whose `probe_path` directory is empty.

## 6. Interaction and layout

- **Hierarchy:** live readout (when present) → verdict → evidence/transcript → history. Not a
  left-nav-first hierarchy; navigation is a thin legend strip, not a sidebar that owns a third of the
  projector.
- **Nav items are gated on pages that actually shipped.** A legend listing four destinations that
  404 reads as broken hardware. This is a hard requirement, not a nicety.
- **Never colour alone.** Every verdict state carries a glyph and a word beside its colour
  (`✓ PASS`, `✗ FAIL`, `⚠ DEGRADED`, `● LIVE`). Load-bearing: pass/fail red-green is the most common
  colourblind failure pair and this product's central output is a pass/fail verdict.
- **Keyboard first.** Every row is reachable and openable without a mouse; focus states are visible
  and part of the instrument language, not a browser default outline that gets reset away.
- **Motion is state change, not decoration.** Transitions ~150–250ms, ease-out, no bounce, no
  elastic. Reduced-motion gets an instant or crossfade alternative. Nothing animates layout
  properties. Content is visible by default — never gated behind a reveal that a headless render or
  a background tab will never fire.
- **Wide content scrolls inside its own container.** Transcripts and tables get
  `overflow-x: auto`; the page body must never scroll horizontally.
- **Destructive and expensive actions confirm**, and the confirmation states the real consequence —
  including that pausing does **not** stop spend, because in-flight trials finish and keep billing.

## 7. Constraints and open decisions

**Binding:** WCAG 2.1 AA (body ≥ 4.5:1, large ≥ 3:1, visible focus, full keyboard, never
colour-alone). React 18 + Vite + TypeScript + Tailwind v3, versions pinned exactly by Task 5 — do
not bump. **Recharts was NOT pinned by Task 5**, which never installed it; it arrived with the
Trends wave under ruling R4-65 and is pinned exactly at `3.10.1` in `ui/package.json` — same rule,
do not bump. Charts follow the same rules: legends present, tooltips keyboard-reachable,
never colour-alone, subtle gridlines, empty-data states that say "no data" rather than rendering an
empty axis frame.

**Open, for the builder to raise rather than invent:**

- Exact chassis grey ramp and the inset window's dark value — must be measured against AA, and
  should be verified once under projection rather than assumed.
- Whether the live readout persists as a slim always-present strip when idle, or disappears entirely.
- Icon set. One family, one stroke weight, SVG only, never emoji.

**Must not be invented:** compare data (there is none), a twincore baseline (not committed), or
discovery findings (the fixture's directory holds only `.gitkeep`).

---

## Direction contract — paste as the first HTML comment in the emitted markup

```
THESIS: The cockpit is a bench instrument, not an admin dashboard: one continuous
  instrument face with rationed danger, refusing the sidebar-table-detail arrangement
  this category always ships.
OWN-WORLD: Cool near-zero-chroma grey chassis (never cream/sand/bone-warm), dark mono
  legends, engraved panel lines instead of cards, status colours keyed to RunStatus
  enum members, ONE inset dark readout window, safety orange rationed to actions that
  spend money or interrupt.
STORY: The operator sees a real system running, then sees exactly what the model said
  when a guardrail failed, and can stop the run knowing what stopping costs.
FIRST VIEWPORT: Thin legend strip; inset dark live-readout window breaking the grid
  (only when a run is active) with the single orange CANCEL key inside it; verdict rows
  beneath in tabular figures, each carrying glyph + word + colour; degraded rows present
  and flat-lined, never hidden.
FORM: Instrument panel — candidate 7 of the grounded list, seed key 3632f7e5, fused with
  design-canon-creator-hardware-bench.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
```
