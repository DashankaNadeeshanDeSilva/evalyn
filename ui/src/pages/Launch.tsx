import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { ApiFailure, apiGet, apiPost, useMeta } from "../api/client";
import {
  RUN_MODES,
  type LaunchRequest,
  type LaunchResponse,
  type MetaResponse,
  type PackAxes,
  type PackListPage,
  type PackRow,
  type RunMode,
} from "../api/types";
import { formatUsd } from "../format";
import { IconAlert, IconRun } from "../components/InstrumentIcon";
import { SafetyKey } from "../components/SafetyKey";

/**
 * The launch console: the one page on this surface that spends money.
 *
 * ## Three interlocks, and none of them is decoration
 *
 * 1. **A pack is named by `id`, never by path.** The list is the allowlist that
 *    `evalyn ui --target` built at start-up, and it is the complete set of
 *    packs a browser may name. `PackRow.path` is a display-safe label with the
 *    home directory collapsed — it is not a usable path and it is never sent
 *    back.
 * 2. **Type-to-confirm.** `LaunchRequest.confirm` must echo `PackRow.name`
 *    exactly or the server answers 400 `launch_refused`. That is what stops a
 *    drive-by `curl` — and a mis-aimed click — from starting a run that bills.
 * 3. **`max_usd` is a ceiling the browser may lower, never raise.** The server
 *    clamps to `min(request, pack.spec.budget.max_usd_per_run)`. The pack's own
 *    ceiling is read and stated rather than assumed, because a discover run
 *    with no stated budget is the one launch that can spend without a bound the
 *    operator chose.
 *
 * ## `GET /api/packs` is an envelope
 *
 * `{items, next_cursor}`, not a bare array — a frozen top-level array could
 * never grow a field. Reading it as an array is a mistake that has already cost
 * this branch a merge repair, so the read below goes through `.items` and the
 * empty case is a real state rather than a crash.
 *
 * ## What this console deliberately refuses to offer
 *
 * A mode it cannot actually launch is shown, disabled, with the reason stated —
 * the same rule the legend strip follows for unshipped destinations. `compare`
 * pairs two existing gate artifacts and this console has no picker for them;
 * inventing a run-id text field would be inviting the operator to paste a
 * string the server will reject. `discover` is refused outright when the server
 * was started without `--allow-discover`.
 *
 * ## Deferred — live checks this cannot make (prerequisite: Task 20)
 *
 * `POST /api/runs` does not exist yet; the only launcher this has met is the
 * MSW handler. The wiring pass must verify against a real `evalyn ui`:
 *
 * 1. The `run_id` in the 202 is the stem of the artifact that later appears, so
 *    the navigation below lands on the run that was actually started.
 * 2. A second concurrent launch answers 409 `busy`, and this page renders that
 *    refusal as a sentence rather than a generic failure.
 * 3. A `discover` request above the pack ceiling is clamped **down** by the
 *    server, and the run that starts reports the clamped figure.
 * 4. `baseline_run_id` — a gate launch from here diffs against nothing today.
 *    The demo's red-diff beat needs a baseline picker, and the picker needs a
 *    committed baseline to pick; neither exists yet.
 * 5. `objectives` and `allow_uncalibrated` are omitted here, so the server's
 *    defaults apply: all objectives, and a refusal on an uncalibrated pack.
 */

function modeRefusal(mode: RunMode, meta: MetaResponse | undefined): string | null {
  if (mode === "compare") {
    return (
      "Compare pairs two gate artifacts that already exist. This console has " +
      "no picker for them yet — launch a compare from the CLI."
    );
  }
  if (mode === "discover") {
    // Unknown is not permission. Until `/api/meta` answers, the console does
    // not know whether this server permits discover, and guessing "yes" would
    // arm the most expensive launch on the surface off an assumption.
    if (meta === undefined) {
      return "This server has not reported whether it permits discover.";
    }
    if (!meta.allow_discover) {
      return "This server was started without --allow-discover.";
    }
  }
  return null;
}

/**
 * A refused launch, as a sentence the operator can act on.
 *
 * **`detail` is absent, not null, when the server has no extra context.**
 * `ApiError.detail` is `str | None = None` and every envelope is rendered with
 * `exclude_none=True` (`ui/redact.py`), so the key simply does not arrive. The
 * first version guarded with `=== null` — false for `undefined` — and printed
 * the literal word `(undefined)` at the end of **every** real refusal. The MSW
 * handler defaulted the field to `null`, which is the only reason that survived
 * to a browser.
 */
function refusalSentence(error: ApiFailure): string {
  // `?? null` is the point: absent and null are the same fact — there is no
  // extra context — and they must have exactly one rendition.
  const detail = error.detail ?? null;
  return (
    `Launch refused — ${error.code ?? error.status}: ${error.message}` +
    (detail === null ? "" : ` (${detail})`)
  );
}

/** A key that snaps to one of a closed set of positions. */
function Detent({
  selected,
  disabled,
  reason,
  onClick,
  children,
}: {
  selected: boolean;
  disabled: boolean;
  reason: string | null;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      data-testid="detent"
      data-value={children}
      aria-pressed={selected}
      disabled={disabled}
      title={reason ?? `Select ${children}`}
      /*
       * The scenario table's key shape, reused rather than reinvented: the
       * engraved rule beneath is the control's only boundary, and the position
       * is discrete — there is no intermediate rendition between two modes.
       *
       * The rule is measured by hand; the contrast guard reads `text-` and
       * `bg-` prefixes only and cannot see a rule set this way (R4-24). On the
       * face at chassis-25: chassis-900 16.37 (selected and hover),
       * chassis-500 4.03 (resting, >= 3:1 for a graphical object),
       * chassis-300 1.55 (disabled, the 1.4.3 inactive-control exemption).
       */
      className={`engrave-b px-3 py-2 text-legend uppercase tracking-legend transition-colors duration-state ${
        disabled
          ? "cursor-not-allowed text-chassis-500 [--rule:theme(colors.chassis.300)]"
          : selected
            ? "text-chassis-900 [--rule:theme(colors.chassis.900)]"
            : "text-chassis-700 hover:text-chassis-900 [--rule:theme(colors.chassis.500)] hover:[--rule:theme(colors.chassis.900)]"
      }`}
      onClick={onClick}
    >
      {children}
      {disabled && reason ? (
        // A disabled control is out of the tab order and its `title` is not
        // announced reliably, so the reason travels as text too.
        <span className="sr-only">{` — ${reason}`}</span>
      ) : null}
    </button>
  );
}

/**
 * The two text fields' shared boundary, measured by hand.
 *
 * An input's border is the **only** thing identifying it as a control, so
 * WCAG 1.4.11 applies at 3:1. The first draft used chassis-400, which measures
 * **2.30** on the face — the exact choice `ScenarioTable` already documents as
 * too light for a control's edge, made again here and caught by looking at the
 * page rather than by any guard, since the contrast test reads `text-` and
 * `bg-` prefixes only. chassis-500 measures **4.03**.
 */
const FIELD_EDGE = "border border-chassis-500 bg-chassis-25";

function Legend({ children }: { children: string }) {
  return (
    <h2 className="text-legend uppercase tracking-legend text-chassis-600">
      {children}
    </h2>
  );
}

export function Launch() {
  const navigate = useNavigate();
  const meta = useMeta();
  const [mode, setMode] = useState<RunMode>("gate");
  const [packId, setPackId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [maxUsd, setMaxUsd] = useState("");

  // Same key and lifetime as the cost chip's read: the allowlist cannot change
  // while the server is running, so the two share one cache entry.
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: () => apiGet<PackListPage>("/packs"),
    staleTime: Infinity,
  });

  const rows: readonly PackRow[] = packs.data?.items ?? [];
  const pack = rows.find((row) => row.id === packId) ?? null;

  const axes = useQuery({
    queryKey: ["pack-axes", pack?.id ?? null],
    enabled: pack !== null && mode === "discover",
    queryFn: () =>
      apiGet<PackAxes>(`/packs/${encodeURIComponent(pack!.id)}/axes`),
    staleTime: Infinity,
  });

  const launch = useMutation({
    mutationFn: (request: LaunchRequest) =>
      apiPost<LaunchResponse>("/runs", request),
    onSuccess: (response) => {
      // The run id is minted before the process starts, so the detail page can
      // subscribe to its event stream before any artifact exists.
      void navigate(`/runs/${encodeURIComponent(response.run_id)}`);
    },
  });

  const ceiling = axes.data?.max_usd_per_run ?? null;
  const spend = Number(maxUsd);
  const spendOk = maxUsd.trim() !== "" && Number.isFinite(spend) && spend > 0;

  const refusal: string | null =
    pack === null
      ? "Select the pack this run should use."
      : mode === "discover" && !spendOk
        ? "Enter the most this discover run may spend, in USD."
        : confirm !== pack.name
          ? `Type the pack name ${pack.name} exactly to arm the launch.`
          : null;

  function submit() {
    if (pack === null || refusal !== null) return;
    const request: LaunchRequest = {
      mode,
      pack_id: pack.id,
      confirm,
      ...(mode === "discover" ? { max_usd: spend } : {}),
    };
    launch.mutate(request);
  }

  return (
    <section className="pb-16">
      <div className="engrave-b rule-major px-4 py-3 sm:px-6">
        <h1 className="text-display uppercase tracking-display">Launch a run</h1>
        <p className="mt-1.5 max-w-[70ch] text-readout text-chassis-600">
          This starts a real evaluation against a real target and spends real
          money on the judge model. Nothing below is a preview.
        </p>
      </div>

      <form
        className="px-4 py-5 sm:px-6"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <fieldset>
          <Legend>Mode</Legend>
          <div className="mt-2 flex flex-wrap gap-4">
            {RUN_MODES.map((member) => {
              const reason = modeRefusal(member, meta.data);
              return (
                <Detent
                  key={member}
                  selected={mode === member}
                  disabled={reason !== null}
                  reason={reason}
                  onClick={() => setMode(member)}
                >
                  {member}
                </Detent>
              );
            })}
          </div>
          {RUN_MODES.map((member) => {
            const reason = modeRefusal(member, meta.data);
            return reason === null ? null : (
              <p
                key={member}
                data-testid={`mode-refusal-${member}`}
                className="mt-2 max-w-[70ch] text-legend text-chassis-600"
              >
                <span className="uppercase tracking-legend text-chassis-900">
                  {member}
                </span>
                {` — ${reason}`}
              </p>
            );
          })}
        </fieldset>

        <fieldset className="engrave-t mt-6 pt-5">
          <Legend>Pack</Legend>
          {packs.isPending ? (
            <p className="mt-2 text-readout text-chassis-600">
              Reading the pack allowlist…
            </p>
          ) : packs.isError ? (
            <p className="mt-2 flex items-start gap-2 text-readout text-chassis-900">
              <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
              {packs.error instanceof ApiFailure
                ? `${packs.error.code ?? packs.error.status}: ${packs.error.message}`
                : "The cockpit could not reach its server."}
            </p>
          ) : rows.length === 0 ? (
            <p className="mt-2 max-w-[70ch] text-readout text-chassis-600">
              This cockpit was started with no pack allowlist, so there is
              nothing it is permitted to launch. Restart it as{" "}
              <span className="text-chassis-900">evalyn ui --target &lt;pack&gt;</span>{" "}
              to launch from here.
            </p>
          ) : (
            <ul className="mt-2">
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    data-testid="pack-key"
                    data-pack-id={row.id}
                    aria-pressed={row.id === packId}
                    onClick={() => {
                      setPackId(row.id);
                      // The interlock is per pack: a name typed for one pack
                      // must not arm a launch of another.
                      setConfirm("");
                    }}
                    className={`engrave-b flex w-full flex-wrap items-baseline gap-x-4 gap-y-1 px-3 py-2.5 text-left transition-colors duration-state ${
                      row.id === packId
                        ? "text-chassis-900 [--rule:theme(colors.chassis.900)]"
                        : "text-chassis-700 hover:text-chassis-900 [--rule:theme(colors.chassis.300)] hover:[--rule:theme(colors.chassis.900)]"
                    }`}
                  >
                    <span className="text-readout">{row.name}</span>
                    <span className="text-legend tabular-nums text-chassis-600">
                      {row.version === null ? "unversioned" : `v${row.version}`}
                    </span>
                    <span className="text-legend tabular-nums text-chassis-600">
                      {`${row.probe_count} probes`}
                    </span>
                    <span className="text-legend text-chassis-600">
                      {row.has_calibration
                        ? "calibrated"
                        : "no calibration record"}
                    </span>
                    {/* A display-safe label with $HOME collapsed. Never joined
                        onto anything, never sent back to the server. */}
                    <span className="break-all text-legend text-chassis-600">
                      {row.path}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        {mode === "discover" ? (
          <fieldset className="engrave-t mt-6 pt-5">
            <Legend>Maximum spend</Legend>
            <label
              htmlFor="max-usd"
              className="mt-2 block max-w-[70ch] text-readout text-chassis-700"
            >
              The most this discover run may spend on Evalyn&rsquo;s own judge
              model, in USD. Required: a discover run with no stated ceiling is
              the one launch on this surface that can spend without a bound the
              operator chose.
            </label>
            <input
              id="max-usd"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={maxUsd}
              onChange={(event) => setMaxUsd(event.target.value)}
              className={`mt-2 w-40 ${FIELD_EDGE} px-2 py-1.5 text-readout tabular-nums text-chassis-900`}
            />
            <p className="mt-2 max-w-[70ch] text-legend text-chassis-600">
              {ceiling === null
                ? "Reading this pack's own ceiling…"
                : `The pack's own ceiling is ${formatUsd(ceiling)} per run. The server clamps this figure down to that, never up.`}
            </p>
          </fieldset>
        ) : null}

        <fieldset className="engrave-t mt-6 pt-5">
          <Legend>Confirm</Legend>
          <label
            htmlFor="confirm-pack"
            className="mt-2 block max-w-[70ch] text-readout text-chassis-700"
          >
            {pack === null
              ? "Select a pack above, then type its name here to arm the launch."
              : `Type ${pack.name} to arm the launch. The server refuses a request whose confirmation does not match the pack.`}
          </label>
          <input
            id="confirm-pack"
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            className={`mt-2 w-72 max-w-full ${FIELD_EDGE} px-2 py-1.5 text-readout text-chassis-900`}
          />
        </fieldset>

        <div className="engrave-t mt-6 flex flex-wrap items-center gap-4 pt-5">
          {/* The one dangerous action on this screen. */}
          {/* `type="submit"` and nothing else: the form's own handler runs the
              launch, so Enter in the confirm field and a click on the key take
              exactly the same path. */}
          <SafetyKey
            type="submit"
            disabled={refusal !== null || launch.isPending}
            refusal={refusal ?? undefined}
          >
            <IconRun className="h-4 w-4 shrink-0" />
            {launch.isPending ? "Launching…" : "Launch run"}
          </SafetyKey>
          {refusal === null ? null : (
            <p data-testid="launch-refusal" className="text-legend text-chassis-600">
              {refusal}
            </p>
          )}
        </div>

        {launch.isError ? (
          <p
            data-testid="launch-error"
            className="mt-4 flex max-w-[70ch] items-start gap-2 text-readout text-chassis-900"
          >
            <IconAlert className="mt-0.5 h-4 w-4 shrink-0" />
            {launch.error instanceof ApiFailure
              ? refusalSentence(launch.error)
              : "The cockpit could not reach its server to start this run."}
          </p>
        ) : null}
      </form>
    </section>
  );
}
