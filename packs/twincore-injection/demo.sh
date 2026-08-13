#!/usr/bin/env bash
# Stage driver for the twincore-injection demo — DO NOT type these commands live.
#
# Why a script and not typing: `--baseline` defaults to the literal
# `runs/baseline.json`, which is pack-agnostic and is NOT keyed on the pack. A
# `evalyn gate --target packs/twincore-injection` typed without `--baseline`
# loads a stale 2026-07-23 example-pack artifact, which raises on load and exits
# 2 with "gate: baseline error: … predates the Plan #2a artifact schema" — a
# setup error on the projector instead of the red diff the demo is about. The
# same applies to `--judge-model`: its default is `mockllm/model`, under which
# the required classifier check on `injection-multiturn-trust-pivot` fails
# closed and reds the gate for a reason that has nothing to do with the target.
#
# Both flags are therefore baked in here and cannot be forgotten.
#
#   ./packs/twincore-injection/demo.sh bless   # ONE billed blessing run; writes the baseline
#   ./packs/twincore-injection/demo.sh run     # rehearsal / live run; gates against the baseline
#
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

PACK="packs/twincore-injection"
BASELINE="ci/baseline-twincore-injection.json"
JUDGE="anthropic/claude-sonnet-5"   # NOT openai/*: the target's generator_family
                                    # is `openai`, so an openai judge prints a
                                    # self-preference-bias warning on stage.

die() { printf 'demo.sh: %s\n' "$*" >&2; exit 3; }

[[ -d "$PACK" ]] || die "pack $PACK not found (repo root resolved to $REPO)"
[[ -n "${ANTHROPIC_API_KEY:-}" ]] || die "ANTHROPIC_API_KEY is not set — the judge model is $JUDGE"

# The pack's allowlist admits ONLY :8000. Fail here with a readable message
# rather than inside the runner.
TARGET_URL="${EVALYN_TARGET_URL:-http://localhost:8000}"
case "$TARGET_URL" in
  http://localhost:8000|http://127.0.0.1:8000) ;;
  *) die "EVALYN_TARGET_URL=$TARGET_URL is not allowlisted by $PACK/target.yaml (only :8000)" ;;
esac
: "${EVALYN_TWIN_SLUG:=eval-twin}"
export EVALYN_TARGET_URL="$TARGET_URL" EVALYN_TWIN_SLUG

MODE="${1:-}"
case "$MODE" in
  bless)
    # Blessing is the only step that CREATES the baseline, so a missing file is
    # expected here — but silently clobbering a good baseline hours before the
    # demo is not. Overwriting is opt-in.
    if [[ -e "$BASELINE" && "${EVALYN_BLESS_OVERWRITE:-}" != "1" ]]; then
      die "$BASELINE already exists; re-bless with EVALYN_BLESS_OVERWRITE=1 if that is intended"
    fi
    mkdir -p "$(dirname "$BASELINE")"
    set -x
    uv run evalyn gate \
      --target "$PACK" \
      --judge-model "$JUDGE" \
      --baseline "$BASELINE" \
      --update-baseline
    ;;
  run)
    # A missing baseline must STOP the run, never fall back to the default path.
    [[ -f "$BASELINE" ]] || die "$BASELINE is missing — run './packs/twincore-injection/demo.sh bless' first (billed). Refusing to fall back to the pack-agnostic default runs/baseline.json."
    set -x
    uv run evalyn gate \
      --target "$PACK" \
      --judge-model "$JUDGE" \
      --baseline "$BASELINE"
    ;;
  preflight)
    # Free: no model calls, nothing billed.
    set -x
    uv run evalyn validate-pack "$PACK"
    uv run evalyn gate --target "$PACK" --judge-model "$JUDGE" --baseline "$BASELINE" --dry-run
    ;;
  *)
    die "usage: $0 {bless|run|preflight}"
    ;;
esac
