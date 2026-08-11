import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Field-level drift guard for the 34 wire models.
 *
 * `types.test.ts` covers the closed enums and the module constants. It does
 * **not** cover model fields, and that gap is the same silently-wrong-mirror
 * failure deferred by one step: renaming `RunSummary.judge_usd` to
 * `judge_cost_usd` in `models.py` alone left that suite fully green, while
 * every page reading `judge_usd` would have quietly rendered `undefined`.
 *
 * The check is a triangle, and all three sides are load-bearing:
 *
 *   models.py  ←→  the frozen literal below  ←→  types.ts (parsed, not imported)
 *
 * `types.ts` is *read as source* rather than imported, because TypeScript
 * interfaces are erased at run time — there is nothing to introspect. Parsing
 * is what lets this file catch a rename on the TypeScript side too, not just
 * on the Python side. The frozen literal in the middle is what a reviewer
 * reads; the two parses are what stop it from becoming a comfortable fiction.
 *
 * Field **order** is asserted, not just membership. Order is how a reviewer
 * diffs the two files side by side, and keeping them aligned costs nothing.
 */

const MODELS_PY = resolve(import.meta.dirname, "../../../../src/evalyn/ui/models.py");
const TYPES_TS = resolve(import.meta.dirname, "../types.ts");

interface Model {
  extends: string | null;
  fields: string[];
}

/**
 * Parse `class X(_Model):` / `class X(SomeModel):` bodies out of `models.py`.
 *
 * Only own fields, never inherited ones — `RunDetail` lists what `RunDetail`
 * declares, exactly as `interface RunDetail extends RunSummary` does. Method
 * bodies cannot collide: a `def` sits at 4 spaces, so its locals are at 8.
 */
function pythonModels(source: string): Record<string, Model> {
  const lines = source.split("\n");
  const out: Record<string, Model> = {};
  for (let i = 0; i < lines.length; i++) {
    const header = /^class (\w+)\((\w+)\):$/.exec(lines[i]!);
    if (!header || header[1] === "_Model") continue;
    const fields: string[] = [];
    for (const line of lines.slice(i + 1)) {
      // The class body ends at the first line back in column 0.
      if (line.trim() !== "" && !/^\s/.test(line)) break;
      const field = /^ {4}([a-z_][a-z0-9_]*): /.exec(line);
      if (field) fields.push(field[1]!);
    }
    out[header[1]!] = {
      extends: header[2] === "_Model" ? null : header[2]!,
      fields,
    };
  }
  return out;
}

/** The same, over `types.ts`. Doc comments start with `/` or `*`, never a name. */
function tsInterfaces(source: string): Record<string, Model> {
  const lines = source.split("\n");
  const out: Record<string, Model> = {};
  for (let i = 0; i < lines.length; i++) {
    const header = /^export interface (\w+)(?: extends (\w+))? \{$/.exec(lines[i]!);
    if (!header) continue;
    const fields: string[] = [];
    for (const line of lines.slice(i + 1)) {
      if (line === "}") break;
      const field = /^ {2}([a-z_][a-z0-9_]*)\??: .+;$/.exec(line);
      if (field) fields.push(field[1]!);
    }
    out[header[1]!] = { extends: header[2] ?? null, fields };
  }
  return out;
}

/**
 * The frozen snapshot — the 34 wire models as `models.py` declares them.
 *
 * `extends: null` means the Python base is `_Model`, which has no fields of its
 * own (only `model_config`), so it has no TypeScript counterpart.
 */
const FROZEN: Record<string, Model> = {
  ApiError: { extends: null, fields: ["code", "message", "detail"] },
  ErrorEnvelope: { extends: null, fields: ["error"] },
  Capabilities: { extends: null, fields: ["transcripts", "trial_records", "hard_metrics"] },
  CheckView: { extends: null, fields: ["check", "tier", "required", "weight", "passed", "score", "turn", "evidence", "unsure", "redacted"] },
  TranscriptTurn: { extends: null, fields: ["role", "text", "redacted"] },
  ProbeRow: { extends: null, fields: ["id", "category", "kind", "safety_critical", "samples", "trials", "expected_trials", "pass_at_k", "pass_k", "mean_score", "unsure_trials", "checks", "trial_epochs"] },
  RunSummary: { extends: null, fields: ["run_id", "mode", "pack_name", "created_at", "status", "degraded", "degraded_reason", "capabilities", "judge_usd", "verdict_hint"] },
  GateVerdict: { extends: null, fields: ["run_id", "exit_code", "failures", "quarantined", "report_md", "baseline_run_id", "redacted"] },
  RunDetail: { extends: "RunSummary", fields: ["pack_hash", "judge_model", "log_path", "rubric_scores_untrusted", "total_unsure_trials", "cancelled", "probes", "redacted", "compare", "discovery"] },
  DiscoverySummary: { extends: null, fields: ["agent_model", "rubric_judge_model", "eval_status", "error_count", "sessions_total", "confirmed_count", "live_spend_usd", "reconciled_spend_usd", "effective_spend_usd", "budget_exhausted", "partial", "objectives", "findings"] },
  RunListPage: { extends: null, fields: ["items", "next_cursor"] },
  TrialView: { extends: null, fields: ["run_id", "probe_id", "epoch", "turns", "session_seconds", "invariant_failures", "checks", "redacted"] },
  ReplayView: { extends: null, fields: ["status", "reproduced", "trials", "pass_k", "pass_at_k", "expected_trials", "checks", "reason"] },
  FindingRow: { extends: null, fields: ["probe_id", "run_id", "objective_id", "confirmed", "probe_path", "category", "safety_critical", "persona_id", "playbook_id", "duplicate_of", "duplicate_reason", "replay_status", "created_at", "redacted"] },
  FindingDetail: { extends: "FindingRow", fields: ["probe_yaml", "provenance", "checks", "turns", "replay"] },
  DiscoveryListPage: { extends: null, fields: ["items", "next_cursor"] },
  CategoryTally: { extends: null, fields: ["wins_a", "wins_b", "ties", "unsure", "flips", "criteria_judged", "flip_rate"] },
  HardMetrics: { extends: null, fields: ["latency_mean_a", "latency_mean_b", "latency_p95_a", "latency_p95_b", "invariant_failures_a", "invariant_failures_b", "trials_a", "trials_b"] },
  Scoreboard: { extends: null, fields: ["run_id", "pack_name", "created_at", "label_a", "label_b", "source_a", "source_b", "created_at_a", "created_at_b", "categories", "hard_metrics", "excluded_pairs", "judge_usd", "rubric_scores_untrusted", "redacted"] },
  TrendPoint: { extends: null, fields: ["run_id", "created_at", "value"] },
  TrendSeries: { extends: null, fields: ["pack_name", "probe_id", "metric", "points"] },
  CriterionCounts: { extends: null, fields: ["hits", "total"] },
  TrustReport: { extends: null, fields: ["pack_name", "judge_model", "agreement", "per_rubric_agreement", "per_criterion_agreement", "per_criterion_counts", "unmatched", "stale", "stale_reason", "calibrated_at", "threshold"] },
  PackRow: { extends: null, fields: ["id", "name", "path", "version", "probe_count", "has_calibration"] },
  PackListPage: { extends: null, fields: ["items", "next_cursor"] },
  ValidationReport: { extends: null, fields: ["pack_id", "ok", "errors", "warnings"] },
  PackAxes: { extends: null, fields: ["pack_id", "objectives", "personas", "playbooks", "max_usd_per_run"] },
  LaunchRequest: { extends: null, fields: ["mode", "pack_id", "confirm", "baseline_run_id", "run_id_a", "run_id_b", "max_usd", "objectives", "allow_uncalibrated"] },
  LaunchResponse: { extends: null, fields: ["run_id"] },
  ControlRequest: { extends: null, fields: ["action"] },
  ControlResponse: { extends: null, fields: ["run_id", "accepted"] },
  RedactionMeta: { extends: null, fields: ["enabled", "marker", "reveal_required"] },
  MetaResponse: { extends: null, fields: ["version", "runs_dir", "packs", "allow_discover", "redaction", "heartbeat_seconds"] },
  HealthResponse: { extends: null, fields: ["ok", "version"] },
};

const PY = pythonModels(readFileSync(MODELS_PY, "utf8"));
const TS = tsInterfaces(readFileSync(TYPES_TS, "utf8"));

describe("model fields match models.py verbatim", () => {
  it("mirrors every model, and mirrors nothing that does not exist", () => {
    // A model added to models.py with no interface — or an interface invented
    // on the TypeScript side — fails here rather than at run time in a page.
    expect(Object.keys(PY).sort()).toEqual(Object.keys(FROZEN).sort());
    expect(Object.keys(TS).sort()).toEqual(Object.keys(FROZEN).sort());
  });

  for (const name of Object.keys(FROZEN)) {
    const frozen = FROZEN[name]!;

    it(`${name}: frozen literal === Python source`, () => {
      expect(PY[name]).toEqual(frozen);
    });

    it(`${name}: frozen literal === types.ts`, () => {
      expect(TS[name]).toEqual(frozen);
    });
  }
});

/**
 * Nullability, over response models only.
 *
 * A Python `X | None` must be a TypeScript `X | null` — a required key holding
 * a nullable value. Getting this backwards is how "this run cannot tell you"
 * silently becomes "0".
 *
 * Request models are exempt by design: `LaunchRequest.objectives` has a
 * non-null Python default (`[]`) but is genuinely optional for a browser to
 * omit, so it is `objectives?:`. That asymmetry is the documented convention in
 * `types.ts`, not an oversight.
 */
describe("nullability matches models.py (response models)", () => {
  const REQUEST_MODELS = new Set(["LaunchRequest", "ControlRequest"]);

  const pySource = readFileSync(MODELS_PY, "utf8");
  const tsSource = readFileSync(TYPES_TS, "utf8");

  function pythonNullable(className: string): Record<string, boolean> {
    const lines = pySource.split("\n");
    const start = lines.findIndex((l) => new RegExp(`^class ${className}\\(\\w+\\):$`).test(l));
    const out: Record<string, boolean> = {};
    for (const line of lines.slice(start + 1)) {
      if (line.trim() !== "" && !/^\s/.test(line)) break;
      const m = /^ {4}([a-z_][a-z0-9_]*): (.+?)(?: = .+)?$/.exec(line);
      if (m) out[m[1]!] = /\| None/.test(m[2]!);
    }
    return out;
  }

  function tsNullable(name: string): Record<string, boolean> {
    const lines = tsSource.split("\n");
    const start = lines.findIndex((l) =>
      new RegExp(`^export interface ${name}(?: extends \\w+)? \\{$`).test(l),
    );
    const out: Record<string, boolean> = {};
    for (const line of lines.slice(start + 1)) {
      if (line === "}") break;
      const m = /^ {2}([a-z_][a-z0-9_]*)(\??): (.+);$/.exec(line);
      if (m) out[m[1]!] = m[2] === "?" || /\| null/.test(m[3]!);
    }
    return out;
  }

  for (const name of Object.keys(FROZEN)) {
    if (REQUEST_MODELS.has(name)) continue;
    it(`${name}: every '| None' is a '| null'`, () => {
      expect(tsNullable(name)).toEqual(pythonNullable(name));
    });
  }
});
