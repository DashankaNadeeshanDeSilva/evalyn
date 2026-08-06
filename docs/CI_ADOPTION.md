# Adopting the Evalyn gate in your CI

Evalyn ships a reusable GitHub Actions workflow —
[`.github/workflows/evalyn-gate.yml`](../.github/workflows/evalyn-gate.yml) — that runs
`evalyn gate` against your product and posts one sticky report comment on the PR.
Evalyn's own CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) calls the same
workflow as a self-test against the bundled toy target, so the reference below is also a
working example.

## Calling the reusable workflow

Your repo needs two things checked in: an Evalyn **target pack** (see
`packs/example/` in the Evalyn repo for the shape) and a **blessed baseline** JSON
(convention: `ci/baseline-<pack>.json`). Evalyn itself must be installable in the job —
the workflow runs `uv sync`, so add `evalyn` to your project's (dev) dependencies.

```yaml
# .github/workflows/evalyn-gate.yml in YOUR repo
name: evalyn-gate

on:
  pull_request:
    # paths-filter recipe: only run the gate when behavior-shaping inputs
    # change — prompts, skills/tools, model constants, the pack itself.
    # Replace these placeholders with your product's real paths.
    paths:
      - "prompts/**"
      - "skills/**"
      - "src/myproduct/model_constants.py"
      - "packs/myproduct/**"
      - "ci/baseline-myproduct.json"

jobs:
  gate:
    permissions:
      contents: read
      pull-requests: write   # the sticky PR comment
    uses: DashankaNadeeshanDeSilva/evalyn/.github/workflows/evalyn-gate.yml@main
    with:
      pack-path: packs/myproduct
      baseline-path: ci/baseline-myproduct.json
      # Optional: bring the product up inside the job. Skip both if the
      # target is already reachable (e.g. a staging URL in the allowlist).
      target-command: "make run-dev-server"
      target-health-url: "http://127.0.0.1:8080/health"
      judge-model: anthropic/claude-3-5-haiku-latest
    secrets:
      EVALYN_JUDGE_API_KEY: ${{ secrets.EVALYN_JUDGE_API_KEY }}
```

Inputs: `pack-path` and `baseline-path` are required; `target-command` (launched in the
background), `target-health-url` (polled up to 60s until it returns **HTTP 200** — point it at a
real health endpoint), `judge-model` (default `mockllm/model`,
which scores classifier checks UNSURE — fine for smoke tests, useless for real judging),
and `python-version` (default `"3.12"`) are optional.

## Secret setup

The judge needs an API key unless you stay on `mockllm/model`. Add
`EVALYN_JUDGE_API_KEY` under **Settings → Secrets and variables → Actions** in your repo
and pass it through as shown above; the workflow exports it as `ANTHROPIC_API_KEY` for
the gate step only. No secret is needed for the mockllm judge — Evalyn's own self-test
runs with zero secrets and zero spend.

## Exit codes: what a red gate means

The job's status is the `evalyn gate` exit code, and the sticky PR comment repeats it
with an explainer:

- **0 — PASS.** No regression vs the blessed baseline.
- **1 — REGRESSION.** The product's behavior changed vs the blessed baseline: a
  safety-critical probe no longer passes every trial (pass^k), or a probe's mean score
  dropped more than the band. This is the signal the gate exists for.
- **2 — SETUP/INFRA.** The eval never (fully) reached the product — stale rubric
  calibration, an unreachable target, budget exhaustion, or a corrupt/pre-#2a baseline.
  **Not a product regression**; fix the setup, don't ship or revert on it.

## The committed-baseline convention

The baseline is the one run artifact you commit on purpose (everything else under
`runs/` stays untracked). To create or refresh it, run the gate locally against a target
state you are deliberately blessing:

```
uv run evalyn gate --target packs/myproduct --baseline ci/baseline-myproduct.json --update-baseline
```

Guard rails on blessing:

- `--update-baseline` **refuses** (exit 2) to bless an untrusted run — uncalibrated
  rubric scores (`--allow-uncalibrated`) or probes with zero scored trials.
  `--force-baseline` is the loud, deliberate escape hatch.
- Blessing a FAIL verdict is allowed but announced (`gate: blessing FAIL verdict …`) —
  it should be a visible, deliberate act, e.g. accepting a known limitation.
- **Staleness:** every artifact records the pack's content hash. When the committed
  baseline's `pack_hash` no longer matches the current pack, the gate prints a loud
  `baseline may be stale` warning — re-bless whenever you change the pack. A stale
  rubric **calibration** record is harder-line: the gate refuses to run rubric checks
  and exits 2 (see the explainer above) until you re-run `evalyn calibrate` or
  explicitly pass `--allow-uncalibrated`.

Baselines deliberately **exclude per-trial transcripts** (`trial_records` is stripped on
save — privacy and size); transcripts live in the run artifacts under `runs/`. Blessing
evidence (pass rates, checks, trial counts) is unaffected.

Review baseline diffs like code: a PR that touches `ci/baseline-*.json` is changing
what "no regression" means.

## `discover` is never in the blocking path

Only `gate` gates. `discover` (Plan #3) is exploratory — it hunts for new failure
modes and by design produces novel, unvetted findings. Run it on a schedule or manually,
triage its output into new pack probes, and let those probes gate. Never wire `discover`
into a required PR check.

**Findings are advisory and never self-adopt.** A confirmed finding is staged as a probe
YAML under `<pack>/discoveries/` and then — budget permitting — replayed once through the
gate's own machinery to record whether it still reproduces. Staging happens *before* the
replay (`discovery/run.py:357-361`), and the replay is skipped outright when it is disabled
or the spend meter is exhausted (`run.py:419-421`, recorded as `ReplaySkipped` and the run
marked partial), so a staged file may carry no replay result at all. `load_pack` globs
`probes/*.yaml` and `probes/*.yml` only (`targets/loader.py:64-66`), so a staged file is
inert either way: it changes no gate verdict and no `pack_fingerprint`. Adoption is a
**human** step — review the file, then `git mv` it into `<pack>/probes/`. From that point
it participates in `gate` (`load_pack` reads the working tree, so it counts before you
commit).

**What adoption actually gates, on day one.** A **safety-critical** adopted probe gates on
`pass^k < 1.0` and ignores the baseline (`engine/gate.py:63-70`) — while the bug is still
there it fails the gate from the first run. A **non**-safety-critical adopted probe has no
baseline entry yet, so a failing score falls to `engine/gate.py:82-83`: it lands in
*Quarantined (review, not blocking)* and leaves **exit 0** until you bless a baseline that
contains it. `discover` emits `safety_critical` (and `samples: 3`) only for the
safety-critical objectives (`discovery/emit.py:193,198`) — so "adopt a finding and CI reds"
is true for those, and not yet true for the rest. Plan accordingly when a finding is meant
to block: adopt it, then re-bless the baseline.

Evalyn's own self-test launches the toy target with `TOY_DISCOVERY_WEAKNESSES=0`
(`.github/workflows/ci.yml:42`) so the planted discover-only weaknesses stay off and
`ci/baseline-example.json` never moves.

## TwinCore adoption

Adopting this workflow for TwinCore is a documented follow-up performed **in the
TwinCore repo** (its pack, its baseline, its secrets), not here. Evalyn's own CI only
self-tests against the bundled toy target with the mockllm judge.
