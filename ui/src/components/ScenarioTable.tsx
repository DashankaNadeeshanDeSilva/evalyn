import type { Capabilities, ProbeRow } from "../api/types";
import { Flatline } from "./Flatline";

/**
 * The probe rows of a gate run, and the keys that open one trial's transcript.
 *
 * ## `pass^k` and `mean_score` sit side by side, on purpose
 *
 * The demo's real failure is `injection-exfil-boundaries` at `pass^k = 0.00`
 * with `mean_score = 0.33`: the model refused correctly in one trial out of
 * three and the probe is safety-critical, so every trial had to pass. Those two
 * numbers disagreeing **is** the argument for `pass^k`, and collapsing them into
 * one figure is the claim Evalyn refuses to make. Neither column is ever a
 * derived blend of the other.
 *
 * ## Layout: no fixed column budget here, deliberately
 *
 * `RunsTable` carries a measured `table-fixed` budget because its columns hold
 * enumerated values whose widest member can be named. This table cannot: a
 * `probe_id` and a `category` are arbitrary strings from the pack, and the
 * corpus already runs to `injection-exfil-boundaries`. `table-fixed` does not
 * clip an over-long cell, it lets it collide silently with its neighbour, so
 * fixing widths against content with no upper bound trades a scrollbar for an
 * illegible row. Auto layout inside the table's own horizontal scroller cannot
 * collide. The numeric columns are `whitespace-nowrap` and `tabular-nums`, so
 * they still read as a graduated instrument face rather than jittering.
 *
 * ## The drill-down is gated on `capabilities`, never on the data
 *
 * `capabilities.trial_records` is the authority on whether
 * `GET /api/runs/{id}/trials/{probe}/{epoch}` can answer at all. Reading
 * `trial_epochs.length` instead happens to work on today's fixtures and is
 * wrong: the contract says a 404 from that route is a **bug in the caller**,
 * because the capability told it not to ask. A disabled key is also not a hidden
 * key — Product Principle 3 is "degrade visibly rather than hide", so the
 * affordance stays, greyed, with the reason attached in both `title` and text.
 */

const COLUMNS = [
  "Probe",
  "Trials",
  "pass^k",
  "pass@k",
  "mean",
  "unsure",
  "Trial transcripts",
] as const;

export interface TrialSelection {
  probeId: string;
  epoch: number;
}

/** A measured value, or an honest flat line — never a substituted zero. */
function Metric({
  name,
  value,
}: {
  name: "pass_k" | "pass_at_k" | "mean_score";
  value: number | null;
}) {
  if (value === null) {
    return (
      <Flatline
        word="unrecorded"
        reason={
          name === "mean_score"
            ? // Two causes, and this layer cannot tell them apart: the engine
              // now records `null` when no trial produced a usable score, and
              // an artifact written before that field existed omits the key —
              // `_recorded` in `ui/index.py` answers `None` for both. Naming
              // only the first would be the stronger, wrong claim on a legacy
              // artifact. What is certainly true is that no mean was measured,
              // which is the part that matters: it is not a zero.
              "no mean was measured — either no trial produced a usable " +
              "score, or this artifact predates the field"
            : `this artifact did not record ${name.replace(/_/g, " ")}`
        }
      />
    );
  }
  return (
    <span
      data-metric={name}
      data-numeric={name}
      className="tabular-nums text-chassis-900"
    >
      {value.toFixed(2)}
    </span>
  );
}

/**
 * Why this probe's drill-down cannot be opened, or `null` when it can.
 *
 * Two different facts, deliberately worded apart: the *artifact* recorded no
 * trials at all, versus *this probe* recorded none in a run that did.
 */
function blockedReason(
  capabilities: Capabilities,
  probe: ProbeRow,
): string | null {
  if (!capabilities.trial_records) {
    return "This artifact has no trial records, so no transcript can be opened. Runs before Plan #2b did not capture them.";
  }
  if (probe.trial_epochs.length === 0) {
    return "This probe recorded no trial for this run, so there is no transcript to open.";
  }
  return null;
}

/**
 * The one key shape, so `all` and `4` read as the same control.
 *
 * A key on a panel: a hard rectangle that snaps between two discrete positions,
 * with no intermediate rendition. Disabled keys keep their shape so the row
 * still reads as an instrument with a channel out, rather than as a row that
 * forgot a control.
 *
 * The engraved rule under each key is that key's only boundary, so it is the
 * graphic that identifies the control and it is measured, by hand — the
 * contrast guard scans `text-` and `bg-` prefixes only and cannot see a rule set
 * through the rule variable (ruling R4-24, and this file's own inventory entry
 * says so).
 *
 * On the face at `chassis-25`:
 *   chassis-900  16.37  the open key, and hover
 *   chassis-500   4.03  the resting key       (>= 3:1, WCAG 1.4.11)
 *   chassis-300   1.55  the disabled key
 *
 * `chassis-400` (2.30) was the first choice for the resting key and is below the
 * 3:1 bar for a graphical object, so it is not used. `chassis-300` on a disabled
 * key is the 1.4.3 exemption for an inactive component, taken deliberately:
 * reading as unavailable is the whole point, and the reason is carried in text
 * either way.
 */
function keyClass(disabled: boolean, open: boolean): string {
  return `min-w-[2.25rem] px-2 py-1 text-legend tabular-nums transition-colors duration-state ${
    disabled
      ? "cursor-not-allowed text-chassis-500 [--rule:theme(colors.chassis.300)]"
      : open
        ? "text-chassis-900 [--rule:theme(colors.chassis.900)]"
        : "text-chassis-700 hover:text-chassis-900 [--rule:theme(colors.chassis.500)] hover:[--rule:theme(colors.chassis.900)]"
  } engrave-b`;
}

function TrialKeys({
  probe,
  capabilities,
  selected,
  allSelected,
  onSelect,
  onSelectAll,
}: {
  probe: ProbeRow;
  capabilities: Capabilities;
  selected: TrialSelection | null;
  /** The probe whose all-trials panel is open, if any. */
  allSelected: string | null;
  onSelect: (selection: TrialSelection) => void;
  onSelectAll: (probeId: string) => void;
}) {
  const blocked = blockedReason(capabilities, probe);
  // No epoch is invented when none was recorded: the single key that stands in
  // for the missing set is labelled, not numbered.
  const epochs: (number | null)[] =
    probe.trial_epochs.length > 0 ? [...probe.trial_epochs] : [null];

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {/*
        Leftmost, and first in the tab order, because it is the question asked
        first: a probe goes red because trials disagreed, and the disagreement
        is only visible with the trials side by side. The numbered keys after it
        are the zoom-in.

        Gated on exactly the same `blockedReason` as they are — a panel offered
        where the capability says no would fire one 404 per trial, and the
        contract calls that a bug in the caller rather than a state.
      */}
      <button
        type="button"
        data-testid="all-trials-key"
        disabled={blocked !== null}
        aria-pressed={allSelected === probe.id}
        title={
          blocked ??
          `Show all ${probe.trial_epochs.length} trials of ${probe.id} together and compare them`
        }
        onClick={() => onSelectAll(probe.id)}
        className={`${keyClass(blocked !== null, allSelected === probe.id)} uppercase tracking-legend`}
      >
        all
        {blocked === null ? null : (
          <span className="sr-only">{` — ${blocked}`}</span>
        )}
      </button>

      {epochs.map((epoch, index) => {
        const isOpen =
          epoch !== null &&
          selected !== null &&
          selected.probeId === probe.id &&
          selected.epoch === epoch;
        const disabled = blocked !== null || epoch === null;
        return (
          <button
            key={epoch ?? `none-${index}`}
            type="button"
            data-testid="trial-key"
            data-epoch={epoch === null ? "" : String(epoch)}
            disabled={disabled}
            aria-pressed={isOpen}
            title={
              blocked ??
              `Open trial ${epoch} of ${probe.id} and read the conversation`
            }
            onClick={
              epoch === null ? undefined : () => onSelect({ probeId: probe.id, epoch })
            }
            className={keyClass(disabled, isOpen)}
          >
            {epoch === null ? "none" : epoch}
            {blocked === null ? null : (
              // `title` is not announced reliably and a disabled control is out
              // of the tab order, so the reason also travels as text.
              <span className="sr-only">{` — ${blocked}`}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function ProbeRowCells({
  probe,
  capabilities,
  selected,
  allSelected,
  onSelect,
  onSelectAll,
}: {
  probe: ProbeRow;
  capabilities: Capabilities;
  selected: TrialSelection | null;
  allSelected: string | null;
  onSelect: (selection: TrialSelection) => void;
  onSelectAll: (probeId: string) => void;
}) {
  return (
    <tr
      data-testid={`probe-row-${probe.id}`}
      data-probe-id={probe.id}
      className="engrave-b align-top transition-colors duration-state hover:[--rule:theme(colors.chassis.700)]"
    >
      <td className="py-2 pl-4 pr-3 sm:pl-6">
        <span className="block break-all text-readout text-chassis-900">
          {probe.id}
        </span>
        <span className="mt-0.5 block text-legend text-chassis-600">
          {probe.category}
          {" · "}
          {probe.kind}
          {probe.safety_critical ? (
            <>
              {" · "}
              {/* Not colour: this is the fact that turns pass^k into a hard
                  gate, and it has to survive a monochrome projector. */}
              <span className="uppercase tracking-legend text-chassis-900">
                safety-critical
              </span>
            </>
          ) : null}
        </span>
      </td>

      <td className="whitespace-nowrap py-2 pr-3 text-readout tabular-nums text-chassis-700">
        {/* `expected_trials: 0` means UNKNOWN on a pre-round-2 artifact — the
            gate skips its incompleteness check there — so it is never rendered
            as an expectation of zero. */}
        {probe.expected_trials === 0
          ? probe.trials
          : `${probe.trials} / ${probe.expected_trials}`}
      </td>

      <td className="whitespace-nowrap py-2 pr-3 text-readout">
        <Metric name="pass_k" value={probe.pass_k} />
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-readout">
        <Metric name="pass_at_k" value={probe.pass_at_k} />
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-readout">
        <Metric name="mean_score" value={probe.mean_score} />
      </td>
      <td className="whitespace-nowrap py-2 pr-3 text-readout tabular-nums text-chassis-700">
        {probe.unsure_trials}
      </td>

      <td className="py-2 pl-3 pr-4 sm:pr-6">
        <TrialKeys
          probe={probe}
          capabilities={capabilities}
          selected={selected}
          allSelected={allSelected}
          onSelect={onSelect}
          onSelectAll={onSelectAll}
        />
      </td>
    </tr>
  );
}

export function ScenarioTable({
  probes,
  capabilities,
  selected,
  allSelected,
  onSelect,
  onSelectAll,
  live = false,
}: {
  probes: readonly ProbeRow[];
  capabilities: Capabilities;
  selected: TrialSelection | null;
  allSelected: string | null;
  onSelect: (selection: TrialSelection) => void;
  onSelectAll: (probeId: string) => void;
  /**
   * Is a process still attached? Then there is **no artifact yet**, and the
   * empty-artifact sentence below would be a claim about a file that does not
   * exist. Same `live` the page hands to `GateRunDetail`, so the two cannot
   * disagree about which run is on the air.
   */
  live?: boolean;
}) {
  if (probes.length === 0) {
    /*
     * Two different facts, and saying the first when the second is true is how
     * a running run ended up reading "This artifact records no probe rows" one
     * line under "the artifact … is written when the run ends" — true, and
     * read by an operator as "this run found nothing".
     */
    return live ? (
      <p
        data-testid="scenario-pending"
        className="engrave-b px-4 py-6 text-readout text-chassis-600 sm:px-6"
      >
        No probe rows yet — this table reads the run's artifact, and the
        artifact is written when the run ends.
      </p>
    ) : (
      <p
        data-testid="scenario-empty"
        className="engrave-b px-4 py-6 text-readout text-chassis-600 sm:px-6"
      >
        This artifact records no probe rows. That is the artifact's own content,
        not a failed read — a run that never scored anything looks exactly like
        this.
      </p>
    );
  }

  return (
    <div data-testid="scenario-table" className="overflow-x-auto">
      <table className="w-full min-w-[64rem] border-collapse text-left">
        <caption className="sr-only">
          Probe rows for this gate run, with per-trial transcript keys.
        </caption>
        <thead>
          <tr className="engrave-b rule-major">
            {COLUMNS.map((label) => (
              <th
                key={label}
                scope="col"
                className={`whitespace-nowrap py-2 text-legend font-normal uppercase tracking-legend text-chassis-600 ${
                  label === "Probe"
                    ? "pl-4 pr-3 sm:pl-6"
                    : label === "Trial transcripts"
                      ? "pl-3 pr-4 sm:pr-6"
                      : "pr-3"
                }`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {probes.map((probe) => (
            <ProbeRowCells
              key={probe.id}
              probe={probe}
              capabilities={capabilities}
              selected={selected}
              allSelected={allSelected}
              onSelect={onSelect}
              onSelectAll={onSelectAll}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
