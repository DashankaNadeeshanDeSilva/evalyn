import { describe, expect, it } from "vitest";

import type { CheckView, FindingRow } from "../api/types";
import {
  adoptionCommand,
  annotationsFor,
  objectiveVocabulary,
  replaySentence,
  tallyFindings,
} from "../discoveries";

/**
 * The discoveries model — the arithmetic and the wording that must not drift.
 *
 * Two things here are load-bearing rather than tidy, and both come from the
 * real staged findings rather than from the fixtures.
 *
 * **A skipped replay is not a failed replay.** `ReplayStatus` carries four
 * members and two of them are skips: `skipped_budget` means the discover run
 * ran out of money before it could try, `skipped_disabled` means nobody asked.
 * Neither is evidence about whether the finding reproduces, and collapsing
 * either into "did not reproduce" would report a verdict the engine never
 * reached — on a page whose whole job is deciding which findings become
 * permanent gates. The real `discovered-pii-leak` finding is the safety-critical
 * one, so this is the exact row where a false "did not reproduce" would talk an
 * operator out of adopting a real PII leak.
 *
 * **An annotation is never invented.** `CheckView.turn` is `null` for
 * whole-session checks — both real staged findings' required checks are of that
 * kind (`rubric:groundedness` and `invariant:no-pii-leak` both grade the session,
 * not a turn). A model that turned `null` into turn 1 would paint a highlight on
 * words no check ever read, which is the fabricated-evidence failure
 * `TranscriptViewer` was built to refuse.
 */

function row(patch: Partial<FindingRow> = {}): FindingRow {
  return {
    probe_id: "discovered-hallucination-4a057400",
    run_id: "20260810T120000000000-abcdef12-twincore",
    objective_id: "hallucination",
    confirmed: true,
    probe_path: "packs/twincore/discoveries/discovered-hallucination-4a057400.yaml",
    category: "grounding",
    safety_critical: false,
    persona_id: "curious-auditor",
    playbook_id: "trust-then-pivot",
    duplicate_of: null,
    duplicate_reason: null,
    replay_status: "reproduced",
    created_at: "2026-08-10T12:00:00.000000+00:00",
    redacted: true,
    ...patch,
  };
}

function check(patch: Partial<CheckView> = {}): CheckView {
  return {
    check: "rubric:groundedness",
    tier: "3",
    required: true,
    weight: 1.0,
    passed: false,
    score: 0.0,
    turn: null,
    evidence: "",
    unsure: false,
    redacted: false,
    ...patch,
  };
}

describe("replaySentence tells a skip from a verdict", () => {
  it("does not report a budget skip as a failure to reproduce", () => {
    const sentence = replaySentence("skipped_budget");
    expect(sentence.toLowerCase()).toContain("budget");
    expect(
      sentence.toLowerCase(),
      "a replay nobody could afford was reported as a replay that failed",
    ).not.toContain("not reproduce");
  });

  it("does not report a disabled replay as a failure to reproduce", () => {
    const sentence = replaySentence("skipped_disabled");
    expect(
      sentence.toLowerCase(),
      "a replay nobody asked for was reported as a replay that failed",
    ).not.toContain("not reproduce");
  });

  it("says plainly when the replay ran and the finding did not come back", () => {
    expect(replaySentence("not_reproduced").toLowerCase()).toContain(
      "did not reproduce",
    );
  });

  it("says plainly when the replay ran and the finding came back", () => {
    expect(replaySentence("reproduced").toLowerCase()).toContain("reproduced");
  });

  /**
   * `null` is a fifth state the enum does not name: the row carries no replay
   * record at all. It must not borrow the wording of any of the four.
   */
  it("states the absence of a replay record rather than borrowing a status", () => {
    const sentence = replaySentence(null).toLowerCase();
    expect(sentence).toContain("no replay");
    expect(sentence).not.toContain("did not reproduce");
  });
});

describe("tallyFindings counts the two axes separately", () => {
  /**
   * The two counts are deliberately **different numbers** here.
   *
   * The real corpus has one confirmed finding and one safety-critical one, so a
   * tally built on the real pair cannot tell the two predicates apart: swapping
   * them leaves both figures at 1 and the assertion passes over a page that is
   * reporting the wrong fact. A third row breaks the tie.
   */
  it("counts confirmed and safety-critical as independent facts", () => {
    const tally = tallyFindings([
      row({ confirmed: true, safety_critical: false }),
      row({
        probe_id: "discovered-pii-leak-0bf80f3b",
        confirmed: false,
        safety_critical: true,
        replay_status: "skipped_budget",
      }),
      row({
        probe_id: "discovered-pii-leak-11112222",
        confirmed: false,
        safety_critical: true,
        replay_status: "skipped_disabled",
      }),
    ]);

    expect(tally.total).toBe(3);
    expect(
      tally.confirmed,
      "the confirmed count was taken from the safety flag",
    ).toBe(1);
    expect(
      tally.safetyCritical,
      "safety-critical was folded into the confirmed count",
    ).toBe(2);
  });

  it("counts a duplicate-flagged finding as a duplicate", () => {
    const tally = tallyFindings([
      row(),
      row({
        probe_id: "discovered-pii-leak-0bf80f3b",
        duplicate_of: "discovered-hallucination-4a057400",
        duplicate_reason: "same objective and near-identical final turn",
      }),
    ]);
    expect(tally.duplicates).toBe(1);
  });

  it("reports zeroes for an empty bench rather than throwing", () => {
    expect(tallyFindings([])).toEqual({
      total: 0,
      confirmed: 0,
      safetyCritical: 0,
      duplicates: 0,
    });
  });
});

describe("objectiveVocabulary", () => {
  it("dedupes and sorts the objectives the loaded rows actually carry", () => {
    const objectives = objectiveVocabulary([
      row({ objective_id: "pii-leak" }),
      row({ objective_id: "hallucination" }),
      row({ objective_id: "pii-leak" }),
    ]);
    expect(objectives).toEqual(["hallucination", "pii-leak"]);
  });

  it("is empty when nothing is staged, so no filter can be offered", () => {
    expect(objectiveVocabulary([])).toEqual([]);
  });
});

describe("annotationsFor never invents a placement", () => {
  /**
   * The guard. Both real findings' required checks are whole-session, so this
   * is the ordinary case rather than the edge — and an annotation carrying a
   * fabricated turn index would be marked on the transcript as though a check
   * had quoted it.
   */
  it("drops whole-session checks instead of pinning them to a turn", () => {
    const annotations = annotationsFor([
      check({
        check: "invariant:no-pii-leak",
        turn: null,
        // Non-empty on purpose. With empty evidence the *other* filter drops
        // this check anyway, and the assertion would pass over a model that
        // pins whole-session checks to turn 1 — the exact fabrication it is
        // here to refuse.
        evidence: "you can reach the team at «redacted:email»",
      }),
    ]);
    expect(
      annotations,
      "a check that read the whole session was pinned to a turn it never quoted",
    ).toEqual([]);
  });

  it("drops a turn-indexed check with no evidence to mark", () => {
    expect(annotationsFor([check({ turn: 2, evidence: "" })])).toEqual([]);
  });

  it("marks a failed required check as the failing tone", () => {
    const [annotation] = annotationsFor([
      check({ turn: 2, evidence: "at Acme Robotics GmbH", passed: false }),
    ]);
    expect(annotation?.tone).toBe("fail");
    expect(annotation?.turn).toBe(2);
    expect(annotation?.evidence).toBe("at Acme Robotics GmbH");
  });

  /**
   * `fail` is rationed by `TranscriptViewer` to a reading that actually went
   * against the run. A check that passed, and a check that abstained
   * (`passed: null`), are both neutral — a wash the eye reads as an alarm on a
   * check nobody failed is the one thing the payload must not do.
   */
  it("keeps a passing check neutral", () => {
    const [annotation] = annotationsFor([
      check({ turn: 1, evidence: "Bremen", passed: true }),
    ]);
    expect(annotation?.tone).toBe("neutral");
  });

  it("keeps an abstaining check neutral rather than reading it as a failure", () => {
    const [annotation] = annotationsFor([
      check({ turn: 1, evidence: "Bremen", passed: null, unsure: true }),
    ]);
    expect(annotation?.tone).toBe("neutral");
  });

  /**
   * The ids must differ for checks that share a **name** as well as a turn. Two
   * differently-named checks separate themselves, so a corpus built from those
   * would pass over an id that is just the check name — and a duplicate React
   * key silently drops the second mark off the transcript.
   */
  it("gives every annotation a distinct id even when two checks are identical", () => {
    const annotations = annotationsFor([
      check({ check: "not_contains:x", turn: 1, evidence: "one" }),
      check({ check: "not_contains:x", turn: 1, evidence: "two" }),
    ]);
    expect(annotations).toHaveLength(2);
    expect(new Set(annotations.map((a) => a.id)).size).toBe(2);
  });
});

describe("adoptionCommand", () => {
  /**
   * The page's one consequential instruction, and it must be correct enough to
   * paste. `discover` writes the same move into every staged file's header:
   * the probe leaves `<pack>/discoveries/` for `<pack>/probes/`.
   */
  it("moves the staged file out of discoveries and into probes", () => {
    expect(
      adoptionCommand(
        "packs/twincore/discoveries/discovered-pii-leak-0bf80f3b.yaml",
      ),
    ).toBe(
      "git mv packs/twincore/discoveries/discovered-pii-leak-0bf80f3b.yaml " +
        "packs/twincore/probes/discovered-pii-leak-0bf80f3b.yaml",
    );
  });

  /**
   * A path the grammar does not recognise gets no command at all. Printing a
   * `git mv` built from a guess would hand the operator a line that silently
   * moves a file somewhere nobody meant.
   */
  it("refuses to guess when the path is not a staged discovery", () => {
    expect(adoptionCommand("packs/twincore/probes/already-adopted.yaml")).toBeNull();
    expect(adoptionCommand("")).toBeNull();
  });
});
