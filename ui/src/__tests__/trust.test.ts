import { describe, expect, it } from "vitest";

import type { TrustReport } from "../api/types";
import { TRUST_NEVER_CALIBRATED, TRUST_REPORT } from "../mocks/fixtures";
import { belowThreshold, buildTrustModel } from "../trust";

/**
 * The judge-trust record, arranged for reading.
 *
 * The wire hands over three flat maps and a list. The shape the operator needs
 * is the one the *threshold* has: it gates on the overall figure and on each
 * rubric's own figure, and never on a single criterion — so the rubric is the
 * level that decides, and the criteria are the diagnosis underneath it.
 *
 * The fixture is transcribed from `packs/twincore/calibration.json`, which is
 * the only calibrated pack in the repository, so these assertions run against
 * the ids the page will actually render: `"<rubric>:<Criterion heading>"`, with
 * spaces and capitals in the second half.
 */

function report(patch: Partial<TrustReport>): TrustReport {
  return { ...TRUST_REPORT, ...patch };
}

describe("the record is grouped by the rubric that the threshold gates on", () => {
  it("files every criterion under the rubric its id names", () => {
    const model = buildTrustModel(TRUST_REPORT);

    expect(model.rubrics.map((r) => r.rubric).sort()).toEqual([
      "completeness",
      "groundedness",
      "honesty",
      "persona",
    ]);
    const persona = model.rubrics.find((r) => r.rubric === "persona")!;
    expect(persona.criteria.map((c) => c.name).sort()).toEqual([
      "First-person fidelity",
      "Tone under refusal",
    ]);
    // The full wire id survives as the identity, because the heading alone is
    // not unique across rubrics and is not what the record is keyed by.
    expect(persona.criteria.map((c) => c.id).sort()).toEqual([
      "persona:First-person fidelity",
      "persona:Tone under refusal",
    ]);
  });

  /**
   * A criterion heading is prose written by whoever wrote the rubric, so it may
   * contain a colon of its own. Splitting on the last one, or on all of them,
   * silently invents a rubric nobody wrote.
   */
  it("splits an id at its first colon, never a later one", () => {
    const model = buildTrustModel(
      report({
        per_criterion_agreement: { "honesty:Calibration: hedging": 0.75 },
        per_criterion_counts: {},
        per_rubric_agreement: { honesty: 0.75 },
      }),
    );

    expect(model.rubrics).toHaveLength(1);
    expect(model.rubrics[0]!.rubric).toBe("honesty");
    expect(model.rubrics[0]!.criteria[0]!.name).toBe("Calibration: hedging");
  });

  /**
   * A rubric the record scored but listed no criterion for is a real state —
   * the gate reads `per_rubric_agreement`, so that rubric can make the whole
   * record stale while contributing no row. Dropping it would hide the reason.
   */
  it("keeps a rubric that carries an agreement but no criteria", () => {
    const model = buildTrustModel(
      report({
        per_rubric_agreement: { ...TRUST_REPORT.per_rubric_agreement, tone: 0.4 },
      }),
    );

    const tone = model.rubrics.find((r) => r.rubric === "tone");
    expect(tone, "a scored rubric vanished because it listed no criteria").toBeDefined();
    expect(tone!.criteria).toEqual([]);
    expect(tone!.agreement).toBe(0.4);
  });
});

describe("the weakest reading leads, at both levels", () => {
  /**
   * The operator opens this page to find what the judge is bad at. Insertion
   * order is the JSON's, which is alphabetical by construction and therefore
   * says nothing — `persona` is last in the file and is tied for weakest.
   */
  it("orders rubrics weakest first, alphabetically within a tie", () => {
    const model = buildTrustModel(TRUST_REPORT);

    expect(model.rubrics.map((r) => r.rubric)).toEqual([
      "completeness",
      "persona",
      "groundedness",
      "honesty",
    ]);
  });

  it("orders criteria within a rubric weakest first", () => {
    const model = buildTrustModel(TRUST_REPORT);

    const persona = model.rubrics.find((r) => r.rubric === "persona")!;
    expect(
      persona.criteria.map((c) => c.name),
      "the criteria kept the record's own order, so the weak one is second",
    ).toEqual(["Tone under refusal", "First-person fidelity"]);
  });

  /** A criterion nobody scored sorts last: it is not the weakest, it is absent. */
  it("puts an unscored criterion after every scored one", () => {
    const model = buildTrustModel(
      report({
        per_criterion_agreement: { "persona:Tone under refusal": 0.5 },
        per_criterion_counts: {
          "persona:Tone under refusal": { hits: 5, total: 10 },
          "persona:First-person fidelity": { hits: 9, total: 10 },
        },
        per_rubric_agreement: { persona: 0.5 },
      }),
    );

    const persona = model.rubrics[0]!;
    expect(persona.criteria.map((c) => c.name)).toEqual([
      "Tone under refusal",
      "First-person fidelity",
    ]);
    expect(persona.criteria[1]!.agreement).toBeNull();
  });
});

describe("every figure is reported beside the evidence behind it", () => {
  /**
   * 82 hits over 88 matched pairs. Eleven anchors x eight criteria, and the
   * pooled fraction is 0.93181818… — the recorded overall agreement exactly.
   * The page shows the counts so nobody reads `100%` on eleven pairs as
   * certainty; it never *derives* the agreement from them.
   */
  it("pools the matched pairs across the whole record", () => {
    const model = buildTrustModel(TRUST_REPORT);

    expect(model.pairs).toEqual({ hits: 82, total: 88 });
  });

  it("pools the matched pairs within each rubric", () => {
    const model = buildTrustModel(TRUST_REPORT);

    const groundedness = model.rubrics.find((r) => r.rubric === "groundedness")!;
    expect(groundedness.pairs).toEqual({ hits: 21, total: 22 });
  });

  /**
   * Pre-pooling records carry `per_criterion` without `per_criterion_counts`,
   * so the counts are genuinely missing rather than zero. A zero here would
   * read as "measured, and nothing agreed".
   */
  it("reports absent counts as absent, never as zero", () => {
    const model = buildTrustModel(report({ per_criterion_counts: {} }));

    expect(model.pairs).toBeNull();
    for (const rubric of model.rubrics) {
      expect(rubric.pairs).toBeNull();
      for (const criterion of rubric.criteria) expect(criterion.counts).toBeNull();
    }
  });

  it("counts the criteria it actually holds rather than a literal", () => {
    expect(buildTrustModel(TRUST_REPORT).criteria).toBe(8);
    expect(
      buildTrustModel(report({ per_criterion_agreement: {}, per_criterion_counts: {} }))
        .criteria,
    ).toBe(0);
  });
});

describe("a never-calibrated record yields nothing to draw", () => {
  it("has no rubrics, no criteria and no pairs", () => {
    const model = buildTrustModel(TRUST_NEVER_CALIBRATED);

    expect(model.rubrics).toEqual([]);
    expect(model.criteria).toBe(0);
    expect(model.pairs).toBeNull();
  });
});

describe("the threshold gates, and it gates exactly", () => {
  /** `is_stale` compares `< AGREEMENT_THRESHOLD`, so equal to it is not below. */
  it("does not call a reading exactly on the threshold a failure", () => {
    expect(belowThreshold(0.85, 0.85)).toBe(false);
    expect(belowThreshold(0.8499, 0.85)).toBe(true);
  });

  it("makes no claim when there is no threshold or no reading", () => {
    expect(belowThreshold(0.1, null)).toBe(false);
    expect(belowThreshold(null, 0.85)).toBe(false);
  });
});
