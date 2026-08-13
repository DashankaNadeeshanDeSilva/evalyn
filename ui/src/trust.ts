import type { CriterionCounts, TrustReport } from "./api/types";

/**
 * `TrustReport` — three flat maps and a list — arranged the way the threshold
 * sees it.
 *
 * `is_stale` in the engine gates on the **overall** agreement and on **each
 * rubric's own** agreement. It does not gate on a single criterion. So the
 * rubric is the level that decides whether the gate will run rubric checks at
 * all, and the criteria beneath it are the diagnosis — which is why this model
 * nests them rather than handing the page one flat table where every row looks
 * equally consequential.
 *
 * Nothing here computes an agreement. The counts are pooled to state a **sample
 * size** beside each figure, because `100%` over eleven pairs and `100%` over
 * four hundred are different claims and the wire reports both the same way.
 */

/** One criterion of one rubric: the diagnosis level. */
export interface CriterionReading {
  /** The wire id, `"<rubric>:<criterion>"`. The identity, and the React key. */
  id: string;
  /** The criterion heading — prose from the rubric, not a slug. */
  name: string;
  /** `null` when the record scores this criterion nowhere. Never `0`. */
  agreement: number | null;
  /** `null` on a record written before pooled counts existed. Never `0 / 0`. */
  counts: CriterionCounts | null;
}

/** One rubric: the level the threshold actually gates on. */
export interface RubricReading {
  rubric: string;
  agreement: number | null;
  /** Pooled from this rubric's criteria. `null` when none carry counts. */
  pairs: CriterionCounts | null;
  criteria: CriterionReading[];
}

export interface TrustModel {
  /** Weakest rubric first: the operator came to find what the judge is bad at. */
  rubrics: RubricReading[];
  /** Read off the record, never written down — a pack's rubrics change. */
  criteria: number;
  /** Pooled across the record. `null` when nothing carries counts. */
  pairs: CriterionCounts | null;
  /** Criterion ids the rubric declares that the record never matched. */
  unmatched: string[];
}

/**
 * `"persona:Tone under refusal"` -> `["persona", "Tone under refusal"]`.
 *
 * The **first** colon, always. A criterion heading is prose written by whoever
 * wrote the rubric and may contain a colon of its own; splitting on the last
 * one invents a rubric nobody wrote. An id with no colon at all cannot come off
 * this route, and if one does it becomes its own rubric rather than being
 * dropped or filed under an invented heading.
 */
function split(id: string): [rubric: string, name: string] {
  const at = id.indexOf(":");
  return at === -1 ? [id, id] : [id.slice(0, at), id.slice(at + 1)];
}

/** `null` unless something was actually counted — a total of zero is not a count. */
function pool(counts: readonly (CriterionCounts | null)[]): CriterionCounts | null {
  const present = counts.filter((c): c is CriterionCounts => c !== null);
  if (present.length === 0) return null;
  return {
    hits: present.reduce((sum, c) => sum + c.hits, 0),
    total: present.reduce((sum, c) => sum + c.total, 0),
  };
}

/** Weakest first; anything unmeasured last; alphabetical within a tie. */
function weakestFirst<T>(
  a: T,
  b: T,
  reading: (item: T) => number | null,
  label: (item: T) => string,
): number {
  const [x, y] = [reading(a), reading(b)];
  if (x === null && y !== null) return 1;
  if (y === null && x !== null) return -1;
  if (x !== null && y !== null && x !== y) return x - y;
  return label(a).localeCompare(label(b));
}

export function buildTrustModel(report: TrustReport): TrustModel {
  const ids = new Set([
    ...Object.keys(report.per_criterion_agreement),
    ...Object.keys(report.per_criterion_counts),
  ]);

  const byRubric = new Map<string, CriterionReading[]>();
  // Every rubric the record scored gets a group even when it lists no
  // criterion: `per_rubric_agreement` is what the gate reads, so such a rubric
  // can make the whole record stale while contributing no row.
  for (const rubric of Object.keys(report.per_rubric_agreement)) {
    byRubric.set(rubric, []);
  }
  for (const id of ids) {
    const [rubric, name] = split(id);
    const group = byRubric.get(rubric) ?? [];
    group.push({
      id,
      name,
      agreement: report.per_criterion_agreement[id] ?? null,
      counts: report.per_criterion_counts[id] ?? null,
    });
    byRubric.set(rubric, group);
  }

  const rubrics: RubricReading[] = [...byRubric.entries()]
    .map(([rubric, criteria]) => ({
      rubric,
      agreement: report.per_rubric_agreement[rubric] ?? null,
      pairs: pool(criteria.map((c) => c.counts)),
      criteria: [...criteria].sort((a, b) =>
        weakestFirst(a, b, (c) => c.agreement, (c) => c.name),
      ),
    }))
    .sort((a, b) => weakestFirst(a, b, (r) => r.agreement, (r) => r.rubric));

  return {
    rubrics,
    criteria: ids.size,
    pairs: pool(rubrics.map((r) => r.pairs)),
    unmatched: report.unmatched,
  };
}

/**
 * Is this reading under the bar the gate holds it to?
 *
 * `is_stale` compares `< AGREEMENT_THRESHOLD`, so a reading exactly on the
 * threshold passes. Nothing is claimed when either side is absent: a record
 * with no threshold has no bar, and a rubric with no reading was not measured.
 */
export function belowThreshold(
  value: number | null,
  threshold: number | null,
): boolean {
  return value !== null && threshold !== null && value < threshold;
}
