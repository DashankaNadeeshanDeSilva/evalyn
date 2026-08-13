import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  CURSOR_SEPARATOR,
  CONTROL_ACTIONS,
  ERROR_CODES,
  EVENT_NAMES,
  HEARTBEAT_SECONDS,
  REDACTION_MARKER_RE,
  REPLAY_STATUSES,
  RUN_ID_PATTERN,
  RUN_ID_RE,
  RUN_MODES,
  RUN_STATUSES,
  TREND_METRICS,
  TURN_ROLES,
  VERDICT_HINTS,
  VERDICT_TIERS,
} from "../types";

/**
 * `types.ts` is a **hand-written mirror** of `src/evalyn/ui/models.py`. Nothing
 * generates it, so nothing but this file stops the two halves of the wire from
 * drifting apart — and a drift in a closed enum is silent: TypeScript happily
 * narrows a union that no longer describes what the server emits, and the page
 * renders a blank badge in front of an operator.
 *
 * The check is deliberately in two layers:
 *
 * 1. **Frozen literals.** Every member set is pasted below as a literal, copied
 *    from `models.py` by hand. This is the snapshot a reviewer reads.
 * 2. **A parse of `models.py` itself.** The literals are then checked against
 *    the actual Python source at test time. Layer 1 alone would compare
 *    TypeScript to TypeScript and pass forever; layer 2 is what makes the test
 *    discriminating — widen a Python enum without touching this file and it
 *    goes red on the next `npm test`.
 */

const MODELS_PY = resolve(import.meta.dirname, "../../../../src/evalyn/ui/models.py");

function modelsSource(): string {
  return readFileSync(MODELS_PY, "utf8");
}

/**
 * Extract the **values** (not the member names) of a `str, Enum` class body.
 *
 * Names and values diverge on purpose in two places — `VerdictTier.tier_1 =
 * "1"` and every `EventName` member — and the wire only ever carries the value.
 */
function pythonEnumValues(source: string, className: string): string[] {
  const lines = source.split("\n");
  const header = lines.indexOf(`class ${className}(str, Enum):`);
  if (header === -1) throw new Error(`no enum class ${className} in models.py`);
  const values: string[] = [];
  for (const line of lines.slice(header + 1)) {
    // The class body ends at the first line back in column 0.
    if (line.trim() !== "" && !/^\s/.test(line)) break;
    const m = /^ {4}([A-Za-z_][A-Za-z0-9_]*) = "([^"]*)"$/.exec(line);
    if (m) values.push(m[2]!);
  }
  if (values.length === 0) throw new Error(`no members parsed for ${className}`);
  return values;
}

/** The frozen snapshot — copied by hand from `models.py`, §3 "Enums". */
const FROZEN = {
  RunMode: ["gate", "compare", "discover"],
  RunStatus: [
    "passed",
    "gate_failed",
    "invalid",
    "running",
    "paused",
    "cancelled",
    "interrupted",
    "failed_to_start",
    "unreadable",
  ],
  ErrorCode: [
    "not_found",
    "unreadable_artifact",
    "pack_error",
    "launch_refused",
    "busy",
  ],
  // STRING-valued on the wire, and that is not an accident of `str, Enum`:
  // `abstained` is a member, so an integer form was never expressible.
  // Never write `tier === 1`.
  VerdictTier: ["1", "2", "3", "abstained"],
  VerdictHint: ["passed", "failed", "unknown"],
  ControlAction: ["pause", "resume", "cancel"],
  ReplayStatus: [
    "reproduced",
    "not_reproduced",
    "skipped_budget",
    "skipped_disabled",
  ],
  TurnRole: ["user", "assistant"],
  TrendMetric: ["mean_score", "pass_k", "pass_at_k", "judge_usd"],
  EventName: [
    "run.started",
    "spend.updated",
    "artifact.written",
    "run.finished",
    "trial.started",
    "turn.sent",
    "turn.received",
    "trial.finished",
    "probe.scored",
    "pair.judged",
    "agent.step",
    "agent.reply",
    "confirm.result",
    "finding.staged",
    "replay.result",
    "control.paused",
    "control.resumed",
    "control.cancelled",
    "heartbeat",
  ],
} as const;

/** The TS side, keyed by the same Python class name. */
const EXPORTED: Record<keyof typeof FROZEN, readonly string[]> = {
  RunMode: RUN_MODES,
  RunStatus: RUN_STATUSES,
  ErrorCode: ERROR_CODES,
  VerdictTier: VERDICT_TIERS,
  VerdictHint: VERDICT_HINTS,
  ControlAction: CONTROL_ACTIONS,
  ReplayStatus: REPLAY_STATUSES,
  TurnRole: TURN_ROLES,
  TrendMetric: TREND_METRICS,
  EventName: EVENT_NAMES,
};

describe("enum members match models.py verbatim", () => {
  const source = modelsSource();

  for (const name of Object.keys(FROZEN) as (keyof typeof FROZEN)[]) {
    it(`${name}: TypeScript union === frozen literal`, () => {
      expect(EXPORTED[name]).toEqual([...FROZEN[name]]);
    });

    it(`${name}: frozen literal === Python source`, () => {
      expect(pythonEnumValues(source, name)).toEqual([...FROZEN[name]]);
    });
  }

  it("covers every str-Enum declared in models.py — no enum is unmirrored", () => {
    const declared = [...source.matchAll(/^class (\w+)\(str, Enum\):$/gm)].map(
      (m) => m[1]!,
    );
    expect(declared.sort()).toEqual(Object.keys(FROZEN).sort());
  });
});

describe("shared constants match models.py", () => {
  const source = modelsSource();

  it("RUN_ID_PATTERN is byte-identical to the Python pattern", () => {
    // Two adjacent string literals inside `RUN_ID_PATTERN = ( ... )`.
    const block = /RUN_ID_PATTERN = \(\n([\s\S]*?)\n\)/.exec(source);
    expect(block).not.toBeNull();
    const python = [...block![1]!.matchAll(/r"([^"]*)"/g)]
      .map((m) => m[1]!)
      .join("");
    expect(RUN_ID_PATTERN).toBe(python);
  });

  it("RUN_ID_RE accepts the canonical and legacy forms and rejects a filename", () => {
    expect(RUN_ID_RE.test("20260804T081544953468-53e4125b-example")).toBe(true);
    expect(RUN_ID_RE.test("20260723T080347-example")).toBe(true);
    // `.json` matches the character class, which is exactly why `isRunId`
    // carries the extra guard that the bare regex cannot express.
    expect(RUN_ID_RE.test("20260723T080347-example.json")).toBe(true);
    expect(RUN_ID_RE.test("../../etc/passwd")).toBe(false);
    // JS `$` anchors to the end of the haystack, matching the Rust engine
    // pydantic uses — unlike Python's `re`, where `$` also matches before a
    // trailing newline. The two sides must accept the same set of strings.
    expect(RUN_ID_RE.test("20260723T080347-example\n")).toBe(false);
  });

  it("HEARTBEAT_SECONDS matches", () => {
    const m = /^HEARTBEAT_SECONDS = ([\d.]+)$/m.exec(source);
    expect(HEARTBEAT_SECONDS).toBe(Number(m![1]));
  });

  it("CURSOR_SEPARATOR matches", () => {
    const m = /^CURSOR_SEPARATOR = "(.)"$/m.exec(source);
    expect(CURSOR_SEPARATOR).toBe(m![1]);
  });

  it("REDACTION_MARKER_RE matches the one and only marker format", () => {
    const m = /^REDACTION_MARKER_RE = re\.compile\(r"([^"]*)"\)$/m.exec(source);
    expect(REDACTION_MARKER_RE.source).toBe(m![1]);
    expect(REDACTION_MARKER_RE.test("«redacted:email»")).toBe(true);
    expect(REDACTION_MARKER_RE.test("«redacted:EMAIL»")).toBe(false);
  });
});
