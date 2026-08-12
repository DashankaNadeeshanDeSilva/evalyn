import { useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiFailure, apiGet } from "../api/client";
import type {
  DiscoveryListPage,
  FindingDetail,
  FindingRow,
} from "../api/types";
import { CheckEvidence } from "../components/CheckEvidence";
import { Detent } from "../components/Detent";
import { Flatline } from "../components/Flatline";
import {
  IconAlert,
  IconCheck,
  IconQuery,
} from "../components/InstrumentIcon";
import { RedactedChip } from "../components/RedactedChip";
import { TranscriptViewer } from "../components/TranscriptViewer";
import {
  adoptionCommand,
  annotationsFor,
  replaySentence,
  tallyFindings,
} from "../discoveries";
import { formatUtc } from "../format";
import { useRevealOnOpen } from "../hooks/useRevealOnOpen";

/**
 * Discoveries: the staging bench.
 *
 * ## This page is not a list of failures. It is a list of pending decisions.
 *
 * `discover` closes the loop by emitting new regression probes back into the
 * pack, and a staged probe is a **file on disk that is not yet a gate**. Every
 * one of them carries its own header saying so, and the header is the
 * authority this page renders from rather than paraphrasing:
 *
 *     # Discovered by Evalyn `discover` — STAGED, not adopted.
 *     # Move this file to ../probes/<id>.yaml to adopt it as a gate probe.
 *     # CAUTION: this file may contain LIVE DATA captured from the target — a
 *     #   leaked value (an email address, a phone number, an internal path) is
 *     #   embedded VERBATIM as a check value, because redacting it would break
 *     #   the outcome-graded confirmation the check exists to make.
 *     #   REVIEW BEFORE COMMITTING OR SHARING. `<pack>/discoveries/*.yaml` is
 *     #   gitignored; moving this file out of it is what removes that guard.
 *
 * So the operator's question here is never "what happened" — it is "should this
 * become a permanent gate, and what am I committing if I say yes". The page is
 * built around that one act: the staging caution is standing rather than
 * dismissible, and the panel prints the exact `git mv` rather than describing
 * it, because a described move gets retyped and a retyped move gets typo'd into
 * the wrong directory.
 *
 * That caution is not theoretical. The real staged `discovered-pii-leak`
 * finding embeds a live email address verbatim as a `not_contains` value, and
 * the only thing standing between it and this repository's history is that
 * `discoveries/` is gitignored.
 *
 * ## Nothing here reveals
 *
 * `RedactionBanner` defers the `reveal_required` clause to "the finding detail
 * view", which is this page — and the answer it gives is **no control**.
 * Revealing is per-object and gated on a token minted at server start and
 * written to stderr; a browser has no way to know it, so any control here would
 * be a text field asking an operator to paste a secret into a page that is
 * about to be projected. The redacted rendition is the only one this page has,
 * and `Discoveries.test.tsx` holds that as a property rather than trusting it
 * to stay true.
 *
 * ## The marker's kind is server vocabulary, and the client does not model it
 *
 * Redacted values arrive spelled `«redacted:<kind>»` and are printed as the
 * bytes they arrived as. There is deliberately no map from kind to a friendlier
 * label: the kinds are `email`, `phone`, `path`, `token` and `check_value` from
 * the classifier plus `too_deep` and `error` from the walker, that list belongs
 * to the server and moves with it, and a client-side table would be a second
 * source of truth that is wrong the first time a kind is added. Every redaction
 * affordance on this page is driven by the `redacted` **flag** instead — the
 * discipline `RedactedChip` already states, and the reason it takes no text.
 *
 * ## No status ink
 *
 * `status-*` is keyed to `RunStatus` members. A finding is not a run state, so
 * the same ruling the trends and judge-trust pages carry applies here, and it
 * costs nothing: safety-critical is a word and a glyph, confirmation is a word
 * and a glyph, and a replay that never ran is a sentence. Strip every colour
 * from this page and not one fact is lost — which is the only way a
 * safety-critical row survives being read from the back of a lit room by
 * someone who cannot separate red from green.
 *
 * Contrast, measured by hand where the guard cannot reach (it reads `text-` and
 * `bg-` prefixes and is blind to `border-*` and `[--rule:…]`). This page sets
 * no ground of its own, so every ink sits on the page face `chassis-25`:
 *
 *   chassis-900 on chassis-25   16.37   probe ids, marks, values      (AA text)
 *   chassis-700 on chassis-25    8.70   the standing caution's prose  (AA text)
 *   chassis-600 on chassis-25    5.98   legends and sentences         (AA text)
 *   chassis-400 on chassis-25    2.30   aria-hidden separators only   (redundant)
 *   chassis-300 rules            1.55   engraved panel lines          (1.4.11 n/a)
 *   chassis-400 rules (major)    2.30   region divisions              (1.4.11 n/a)
 *   decoration-chassis-500       4.03   the underline marking a control
 *
 * The two rule figures are below 3:1 on purpose and are not affordances: a
 * panel line divides regions that are already divided by heading and spacing,
 * and no rule on this page is the sole mark identifying anything. The
 * underline is, which is why it is `chassis-500` and not lighter.
 */

function Legend({ children }: { children: string }) {
  return (
    <h2 className="text-legend uppercase tracking-legend text-chassis-600">
      {children}
    </h2>
  );
}

/** The readout's separator. Decorative, and announced as nothing. */
function Dot() {
  return (
    <span aria-hidden="true" className="mx-2 text-chassis-400">
      ·
    </span>
  );
}

/**
 * One labelled reading.
 *
 * `prose` picks how the value breaks, and it is not cosmetic. An id or a path
 * has no spaces, so it must break mid-token or it forces the page sideways —
 * but a *sentence* broken mid-token is unreadable, and one provenance value is
 * a sentence: `confirmation` carries the engine's own line, which on the real
 * `discovered-hallucination` finding runs past 200 characters
 * (`confirmed: required rubric:groundedness FAILED (medians={…})`). Breaking
 * that at arbitrary characters would shred the only human-readable account of
 * why the finding was confirmed.
 */
function Field({
  label,
  testId,
  prose = false,
  children,
}: {
  label: string;
  testId?: string;
  prose?: boolean;
  children: ReactNode;
}) {
  return (
    <div data-testid={testId} className="py-1">
      <dt className="text-legend uppercase tracking-legend text-chassis-600">
        {label}
      </dt>
      <dd
        className={`mt-0.5 text-readout text-chassis-900 ${prose ? "break-words" : "break-all"}`}
      >
        {children}
      </dd>
    </div>
  );
}

/**
 * The one mark that has to survive the back of the room.
 *
 * A safety-critical probe gates on `pass^k` — every trial must pass — so one
 * deviating trial fails the whole probe, and adopting one of these is a
 * materially bigger commitment than adopting an advisory probe. It is therefore
 * the single most consequential fact in a row, and it is carried by four
 * channels at once, none of them colour: a glyph, a word, a size step above the
 * rest of the row's labels, and a weight step. Greyscale it, blur it, or read
 * it from twelve metres and it is still the row that is different.
 */
function SafetyCriticalMark() {
  return (
    <span
      data-testid="safety-critical-mark"
      title="Gates on pass^k — every trial must pass, so one deviating trial fails the whole probe."
      className="inline-flex items-center gap-1.5 whitespace-nowrap text-panel font-semibold uppercase tracking-panel text-chassis-900"
    >
      <IconAlert className="h-5 w-5 shrink-0" />
      safety-critical
    </span>
  );
}

export function Discoveries() {
  const [objective, setObjective] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  /*
   * The key that opened the panel, so closing it can hand the keyboard back.
   * Without this, closing drops the operator at the top of the document with
   * the row they were reading scrolled away — the same defect in reverse that
   * `useRevealOnOpen` exists to fix on the way in.
   */
  const opener = useRef<HTMLButtonElement | null>(null);

  const bench = useInfiniteQuery({
    queryKey: ["discoveries", objective],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams();
      if (objective !== null) query.set("objective", objective);
      // The page param IS the server's `next_cursor`, carried verbatim. Nothing
      // here parses, compares or constructs one: the bare-timestamp form is
      // tie-unsafe and the server rejects it loudly.
      if (pageParam !== null) query.set("before", pageParam);
      const qs = query.toString();
      return apiGet<DiscoveryListPage>(`/discoveries${qs ? `?${qs}` : ""}`);
    },
    getNextPageParam: (last: DiscoveryListPage) => last.next_cursor,
  });

  const rows: FindingRow[] = bench.data?.pages.flatMap((page) => page.items) ?? [];

  /*
   * The filter's positions, accumulated rather than derived.
   *
   * `?objective=` is a **server-side** filter, so the rows on screen while a
   * filter is active are exactly the ones that match it — deriving the
   * positions from the current rows would delete every other position the
   * moment one was chosen, which is a selector that destroys itself on first
   * use. The set only ever grows.
   *
   * Written during render on purpose, and safe to be: adding a value already
   * present is a no-op, so a double-invoked render produces the identical set.
   * An effect would be a second commit for a value this render already has.
   */
  const seen = useRef<string[]>([]);
  for (const row of rows) {
    if (!seen.current.includes(row.objective_id)) {
      seen.current = [...seen.current, row.objective_id].sort();
    }
  }
  const vocabulary = seen.current;

  const reading = bench.isPending;
  const failure = bench.error;
  const tally = tallyFindings(rows);

  function choose(next: string | null) {
    setObjective(next);
    // The open finding may not survive the filter; an orphaned panel below a
    // list that no longer contains its row is worse than no panel.
    setSelected(null);
  }

  function toggle(probeId: string, key: HTMLButtonElement) {
    opener.current = key;
    setSelected((current) => (current === probeId ? null : probeId));
  }

  function close() {
    setSelected(null);
    opener.current?.focus();
  }

  return (
    <section className="pb-16">
      <div className="engrave-b flex flex-wrap items-baseline gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
        <h1 className="text-display uppercase tracking-display">Discoveries</h1>

        <p
          data-testid="discoveries-readout"
          className="text-legend text-chassis-600"
        >
          {reading ? (
            "reading the staging directory…"
          ) : failure ? (
            "the staging directory could not be read"
          ) : tally.total === 0 ? (
            "nothing is staged"
          ) : (
            <>
              <Count value={tally.total} /> staged
              <Dot />
              <Count value={tally.confirmed} /> confirmed
              <Dot />
              <Count value={tally.safetyCritical} /> safety-critical
              {tally.duplicates > 0 ? (
                <>
                  <Dot />
                  <Count value={tally.duplicates} /> flagged duplicate
                </>
              ) : null}
            </>
          )}
        </p>
      </div>

      {vocabulary.length > 0 ? (
        <div
          data-testid="discoveries-objective"
          className="engrave-b flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6"
        >
          <Legend>Objective</Legend>
          <div className="flex flex-wrap">
            <Detent selected={objective === null} onClick={() => choose(null)}>
              All
            </Detent>
            {vocabulary.map((name) => (
              <Detent
                key={name}
                selected={objective === name}
                onClick={() => choose(name)}
              >
                {name}
              </Detent>
            ))}
          </div>
        </div>
      ) : null}

      {/*
        Standing, never dismissible, and never rendered over an empty bench —
        a caution about files that do not exist is the noise that teaches an
        operator to stop reading the one that matters.
      */}
      {!reading && !failure && rows.length > 0 ? (
        <p
          data-testid="staging-notice"
          className="engrave-b max-w-[74ch] px-4 py-3 text-readout text-chassis-700 sm:px-6"
        >
          <span className="uppercase tracking-legend text-chassis-900">
            Staged, not adopted
          </span>
          <Dot />
          These files may hold live data captured from the target — a leaked
          address, number or internal path is stored verbatim as a check value,
          because redacting it would break the confirmation the check exists to
          make. They sit in a <strong className="font-semibold">gitignored</strong>{" "}
          directory, and adopting one moves it out, which is exactly what removes
          that guard. Review before committing or sharing.
        </p>
      ) : null}

      {failure ? (
        <p
          data-testid="discoveries-error"
          className="engrave-b flex items-start gap-2 px-4 py-8 text-readout text-chassis-900 sm:px-6"
        >
          {/* The glyph carries the alarm, so the message is never colour alone,
              and no status ink enters: a directory that cannot be read is not a
              run state. */}
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {failure instanceof ApiFailure
            ? `The staging directory could not be read (${failure.code ?? failure.status}): ${failure.message}`
            : "The cockpit could not reach its server. Is `evalyn ui` still running?"}
        </p>
      ) : reading ? (
        <p className="px-4 py-8 text-readout text-chassis-600 sm:px-6">
          Reading the staging directory…
        </p>
      ) : (
        <div data-testid="discoveries-bench">
          {rows.length === 0 ? (
            <Empty objective={objective} />
          ) : (
            <ul className="engrave-t">
              {rows.map((row) => (
                <li key={row.probe_id}>
                  <Row
                    row={row}
                    open={selected === row.probe_id}
                    onToggle={toggle}
                  />
                  {selected === row.probe_id ? (
                    <Panel row={row} onClose={close} />
                  ) : null}
                </li>
              ))}
            </ul>
          )}

          {bench.hasNextPage ? (
            <div className="engrave-b px-4 py-3 sm:px-6">
              <button
                type="button"
                data-testid="discoveries-more"
                disabled={bench.isFetchingNextPage}
                onClick={() => void bench.fetchNextPage()}
                className="text-legend uppercase tracking-legend text-chassis-900 underline decoration-chassis-500 underline-offset-4 transition-colors duration-state hover:decoration-chassis-900"
              >
                {bench.isFetchingNextPage
                  ? "reading the next page…"
                  : "Load more findings"}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

/** A figure, in the ink figures carry, with tabular digits so columns hold. */
function Count({ value }: { value: number }) {
  return <span className="tabular-nums text-chassis-900">{value}</span>;
}

/**
 * An empty bench, written as a complete statement with its recovery.
 *
 * This is the ordinary rendition against a clean checkout, not an edge case:
 * `<pack>/discoveries/` is gitignored, so nothing is staged until someone runs
 * `discover` on this machine. A table frame with no rows would read as a page
 * that failed rather than a directory that is legitimately empty — the same
 * correction the judge-trust page carries for a pack nobody has calibrated.
 */
function Empty({ objective }: { objective: string | null }) {
  return (
    <div
      data-testid="discoveries-empty"
      className="flex items-start gap-2.5 px-4 py-8 sm:px-6"
    >
      <IconQuery className="mt-1 h-5 w-5 shrink-0 text-chassis-600" />
      <div className="max-w-[70ch]">
        <p className="text-panel text-chassis-900">
          {objective === null
            ? "Nothing is staged"
            : `Nothing is staged for ${objective}`}
        </p>
        <p className="mt-2 text-readout text-chassis-700">
          {objective === null
            ? "Findings appear here after `evalyn discover` hunts this pack and " +
              "stages a candidate probe for one. The staging directory is " +
              "gitignored, so a fresh checkout always starts empty."
            : "Other objectives may still have findings — the filter asks the " +
              "server, so this is the whole answer for this one. `evalyn " +
              "discover` is what stages more."}
        </p>
      </div>
    </div>
  );
}

/**
 * One staged finding.
 *
 * Three lines, in the order the adoption decision is made: what it is, what the
 * run established about it, and where the file lives.
 */
function Row({
  row,
  open,
  onToggle,
}: {
  row: FindingRow;
  open: boolean;
  onToggle: (probeId: string, key: HTMLButtonElement) => void;
}) {
  return (
    <div
      data-testid="finding-row"
      data-probe={row.probe_id}
      data-safety={row.safety_critical ? "critical" : "ordinary"}
      /* Safety-critical rows close on a major rule. The heavier panel line is
         redundant beside the mark and the word — it is the fourth channel, not
         the carrier. */
      className={`engrave-b px-4 py-3 sm:px-6 ${row.safety_critical ? "rule-major" : ""}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <button
          type="button"
          aria-expanded={open}
          onClick={(event) => onToggle(row.probe_id, event.currentTarget)}
          /* The underline is the only mark saying this id is a control, which
             is WCAG 1.4.11's graphical object identifying a control — so it is
             `chassis-500` (4.03) and deepens on hover rather than fading. */
          className="break-all text-panel text-chassis-900 underline decoration-chassis-500 underline-offset-4 transition-colors duration-state hover:decoration-chassis-900"
        >
          {row.probe_id}
        </button>
        {row.safety_critical ? <SafetyCriticalMark /> : null}
        {/* Off the flag, never sniffed out of the text. */}
        {row.redacted ? <RedactedChip what="this finding" /> : null}
      </div>

      <p className="mt-1.5 flex flex-wrap items-center gap-x-1 text-legend text-chassis-600">
        <span className="inline-flex items-center gap-1.5 text-chassis-900">
          {row.confirmed ? (
            <IconCheck className="h-4 w-4 shrink-0" />
          ) : (
            /* Not the cross. Nothing failed — the run did not reach a
               confirmation, and a negative mark would be a different claim. */
            <IconQuery className="h-4 w-4 shrink-0" />
          )}
          {row.confirmed ? "confirmed" : "unconfirmed"}
        </span>
        <Dot />
        <span>{replaySentence(row.replay_status)}</span>
      </p>

      {row.duplicate_of !== null ? (
        <p
          data-testid="finding-duplicate"
          className="mt-1.5 flex flex-wrap items-baseline gap-x-2 text-legend text-chassis-600"
        >
          <span className="uppercase tracking-legend text-chassis-900">
            Duplicate
          </span>
          <span className="break-all">{`of ${row.duplicate_of}`}</span>
          <span>
            {row.duplicate_reason === null
              ? "— no reason was recorded"
              : `— ${row.duplicate_reason}`}
          </span>
        </p>
      ) : null}

      <dl className="mt-1.5 grid grid-cols-1 gap-x-8 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Objective">{row.objective_id}</Field>
        <Field label="Category">
          {row.category === null ? (
            <Flatline
              variant="n/a"
              word="uncategorised"
              reason="this finding carries no category"
            />
          ) : (
            row.category
          )}
        </Field>
        {/*
          Stated in words even when it is false. A missing mark and an
          unrendered mark look identical, which is `Flatline`'s whole lesson
          applied to a boolean.
        */}
        <Field label="Safety" testId="finding-safety">
          {row.safety_critical
            ? "safety-critical — gates on pass^k"
            : "not safety-critical"}
        </Field>
        <Field label="Staged">
          {row.created_at === null ? (
            <Flatline
              variant="dead"
              word="unrecorded"
              reason="this finding carries no creation timestamp"
            />
          ) : (
            <span className="tabular-nums">{formatUtc(row.created_at)}</span>
          )}
        </Field>
        <Field label="Persona">{row.persona_id}</Field>
        <Field label="Playbook">{row.playbook_id}</Field>
        {/*
          The path gets the whole row, not a two-column span. Measured at 1440:
          the span offers ~620px and the path needs ~691px, so it broke
          mid-identifier — `…-abcd123` / `4.yaml` — which turns the one value an
          operator has to retype or `git mv` into something that reads like two
          different files. Full width clears it at 820 and at 1440 both.
        */}
        <div className="col-span-full py-1">
          <dt className="text-legend uppercase tracking-legend text-chassis-600">
            File
          </dt>
          <dd className="mt-0.5 break-all text-readout text-chassis-900">
            {row.probe_path}
          </dd>
        </div>
      </dl>
    </div>
  );
}

/**
 * The finding, opened.
 *
 * Rendered immediately beneath its own row rather than below the whole list, so
 * the answer to a click appears where the click was — and still handed to
 * `useRevealOnOpen`, because a row twenty findings down still opens below the
 * fold. Content-in-the-DOM is not content-on-the-screen; that lesson cost a
 * rehearsal.
 *
 * The panel is present from the first frame, before the read lands, so focus
 * has somewhere to go immediately rather than after a round trip.
 */
function Panel({ row, onClose }: { row: FindingRow; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["discovery", row.probe_id],
    queryFn: () =>
      apiGet<FindingDetail>(
        `/discoveries/${encodeURIComponent(row.probe_id)}`,
      ),
  });

  const panel = useRevealOnOpen(row.probe_id);
  const found = detail.data ?? null;
  const move = found === null ? null : adoptionCommand(found.probe_path);

  return (
    <section
      ref={panel}
      tabIndex={-1}
      data-testid="finding-panel"
      data-probe={row.probe_id}
      aria-label={`Finding ${row.probe_id}`}
      className="engrave-t rule-major"
    >
      <div className="engrave-b flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <div>
          <p className="text-legend uppercase tracking-legend text-chassis-600">
            Staged probe
          </p>
          <h2 className="mt-1 break-all text-panel text-chassis-900">
            {row.probe_id}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-legend uppercase tracking-legend text-chassis-900 underline decoration-chassis-500 underline-offset-4 transition-colors duration-state hover:decoration-chassis-900"
        >
          Close
        </button>
      </div>

      {detail.isPending ? (
        <p className="px-4 py-6 text-readout text-chassis-600 sm:px-6">
          Reading the staged file…
        </p>
      ) : detail.error ? (
        <p
          data-testid="finding-error"
          className="flex items-start gap-2 px-4 py-6 text-readout text-chassis-900 sm:px-6"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {detail.error instanceof ApiFailure
            ? `This finding could not be read (${detail.error.code ?? detail.error.status}): ${detail.error.message}`
            : "The cockpit could not reach its server. Is `evalyn ui` still running?"}
        </p>
      ) : found === null ? null : (
        <>
          {move === null ? null : (
            <div className="engrave-b px-4 py-3 sm:px-6">
              <p className="text-legend uppercase tracking-legend text-chassis-600">
                Adopt it as a gate probe
              </p>
              {/*
                The exact line, not a description of it. A described move gets
                retyped, and a retyped move lands in the wrong directory — this
                one takes a file out of a gitignored path, so the cost of a typo
                is a live email address in the repository's history.
              */}
              {/*
                Wrapped, not scrolled. The line is ~130 characters and the two
                halves of it are the whole message — *from* `discoveries/`,
                *to* `probes/`. Behind a horizontal scrollbar the destination is
                the part that falls off the right edge, which on a projector
                means the audience sees a `git mv` whose target nobody can read.
                Wrapping keeps both paths on screen and copies back as one line,
                because the break is the browser's and not a newline.
              */}
              <code
                data-testid="adopt-command"
                className="mt-1 block whitespace-pre-wrap break-all text-readout text-chassis-900"
              >
                {move}
              </code>
              <p className="mt-1.5 max-w-[70ch] text-legend text-chassis-600">
                Until then it is staged only: the gate does not run this probe,
                and the file is not tracked.
              </p>
            </div>
          )}

          <div className="engrave-b px-4 py-3 sm:px-6">
            <Legend>Provenance</Legend>
            {Object.keys(found.provenance).length === 0 ? (
              <p className="mt-1 text-readout text-chassis-600">
                The staged file carried no provenance header.
              </p>
            ) : (
              /*
                Two columns, not four. Provenance is eight keys and one of them
                is a long sentence — four columns would give that sentence a
                ~180px gutter on a projector and a column of shredded prose.
              */
              <dl className="mt-1 grid grid-cols-1 gap-x-8 sm:grid-cols-2">
                {Object.entries(found.provenance).map(([key, value]) => (
                  <Field key={key} label={key.replace(/_/g, " ")} prose>
                    {value}
                  </Field>
                ))}
              </dl>
            )}
          </div>

          <div className="engrave-b px-4 py-3 sm:px-6">
            <Legend>Replay</Legend>
            <p className="mt-1 text-readout text-chassis-900">
              {replaySentence(found.replay?.status ?? row.replay_status)}
            </p>
            {found.replay === null ||
            found.replay.trials === null ? null : (
              <p className="mt-1 text-legend text-chassis-600">
                <span className="tabular-nums text-chassis-900">
                  {found.replay.trials}
                </span>
                {found.replay.trials === 1 ? " trial" : " trials"}
                {found.replay.expected_trials === null
                  ? ""
                  : ` of ${found.replay.expected_trials} expected`}
                {found.replay.reason === "" ? "" : ` — ${found.replay.reason}`}
              </p>
            )}
          </div>

          <div>
            <div className="engrave-b px-4 py-3 sm:px-6">
              <Legend>Checks</Legend>
            </div>
            {found.checks.length === 0 ? (
              /*
                Not "the probe declares no checks" — it declares them, and they
                are in the staged file below. `checks` is flattened off the
                *replay*, so an empty list means nothing scored them, which is
                the ordinary case for a finding whose replay was skipped. The
                two facts have different recoveries and only one of them is
                true here.
              */
              <p className="max-w-[70ch] px-4 py-4 text-readout text-chassis-600 sm:px-6">
                Nothing scored this finding. These are replay results, and this
                finding&rsquo;s replay did not run — the probe&rsquo;s own check
                definitions are in the staged file below.
              </p>
            ) : (
              <ul>
                {found.checks.map((check, index) => (
                  <CheckEvidence key={`${index}:${check.check}`} check={check} />
                ))}
              </ul>
            )}
          </div>

          <div>
            <div className="engrave-b px-4 py-3 sm:px-6">
              <Legend>The prompts that produced it</Legend>
              {/*
                Named for what it actually is. The staged file records the user
                side of the hunt — the messages the target answered — and the
                target's replies are not in it at all, so every turn here is a
                `user` turn. Calling this region "the session" would leave a
                column of prompts with no answers reading as a transcript that
                failed to load, on the one page where a missing reply is the
                difference between a finding and a rumour.
              */}
              <p className="mt-1 max-w-[70ch] text-legend text-chassis-600">
                The staged file records the prompts the hunt sent, not the
                target&rsquo;s replies. What it said back is in the discover
                run&rsquo;s own transcript.
              </p>
            </div>
            <TranscriptViewer
              turns={found.turns}
              annotations={annotationsFor(found.checks)}
              emptyReason="The staged file records no prompts for this finding."
            />
          </div>

          <div className="engrave-t px-4 py-3 sm:px-6">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Legend>The staged file</Legend>
              {found.redacted ? <RedactedChip what="this file" /> : null}
            </div>
            {/*
              `RedactionBanner` defers the reveal clause to "the finding detail
              view", and this is it. The answer is that there is no reveal:
              `GET /api/discoveries/{probe_id}` reads no header and honours no
              token — redaction is unconditional on that route — so the state is
              *stated* rather than offered as a control that would do nothing.
              The recovery is real and deliberately points off-screen: the
              verbatim value is in the file on the machine that ran `discover`.
            */}
            {found.redacted ? (
              <p
                data-testid="finding-no-reveal"
                className="mt-1.5 max-w-[70ch] text-legend text-chassis-600"
              >
                Redacted values cannot be revealed from the cockpit. The
                verbatim value is in this file on the machine that ran{" "}
                <code className="text-chassis-900">discover</code>.
              </p>
            ) : null}
            {/*
              The bytes as served. Wide content scrolls inside its own
              container; the page body never scrolls sideways.
            */}
            <pre
              data-testid="finding-yaml"
              className="mt-1.5 overflow-x-auto whitespace-pre text-readout text-chassis-900"
            >
              {found.probe_yaml}
            </pre>
          </div>
        </>
      )}
    </section>
  );
}
