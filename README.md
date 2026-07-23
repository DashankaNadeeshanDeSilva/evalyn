# Evalyn

Standalone, project-agnostic evaluation agent for LLM-powered products. `evalyn gate` drives a
product's live chat API, scores replies (deterministic + classifier-judge tiers on the Inspect AI
spine), and returns a diffable artifact + CI exit code.

## Quickstart (reference target)

    uv sync
    uv run python examples/toy_target.py          # terminal 1: the demo product
    export EVALYN_TARGET_URL=http://127.0.0.1:8899 # terminal 2
    uv run evalyn validate-pack packs/example      # task-health check
    uv run evalyn gate --target packs/example      # run the suite

Note: with the default `mockllm/...` judge model, classifier checks fail closed (scored UNSURE) —
pass a real `--judge-model` to get classifier scoring.

Safety-critical probes are gated on **pass^k** (must pass every trial); quality probes diff their
mean against a committed baseline; capability probes never fail the build. See
`docs/2026-07-21-evalyn-design.md` for the full design.

Pack-authoring note: `budget` caps (`max_usd_per_run`, `max_turns_per_session`) and per-check
`weight` are declarative-only for now — parsed and validated, but not yet enforced or scored
(their consumers arrive in Plan #2). Also, every probe currently runs at the pack-wide maximum
sample count (Inspect epochs), so declaring a higher `samples` on one probe raises call volume
for all probes.
