import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../api/client";
import type { PackAxes, PackListPage } from "../api/types";
import { formatUsd } from "../format";
import { Flatline } from "./Flatline";

/**
 * What this run cost Evalyn, against the ceiling its pack allows.
 *
 * Product Principle 4 is "be honest about cost", and a bare figure is not
 * honest enough on its own: `$0.0138` means nothing until you know whether the
 * pack's ceiling was two dollars or two cents. So the chip reads the ceiling
 * from the pack itself rather than asking the operator to remember it.
 *
 * ## Three states, and the third is the one that must not lie
 *
 * The ceiling comes from `GET /api/packs` (the start-time allowlist built from
 * `evalyn ui --target`) joined by **name** to `GET /api/packs/{id}/axes`. A run
 * artifact records a `pack_name`, not a `pack_id`, and the allowlist is the
 * only place a browser may learn an id — so a run whose pack is not currently
 * served simply has no ceiling available.
 *
 * That is the demo's real case, not a hypothetical: the twincore runs in
 * `runs/` were produced by a pack that is very unlikely to be on the running
 * server's `--target` list. The chip says the ceiling is **unknown** there. It
 * does not fall back to a default, and it does not quietly drop the comparison
 * and show a bare number as though no ceiling existed.
 *
 * `pending` is a real third state rather than a flicker of `unknown`: the run
 * detail resolves before the pack allowlist does, and "unknown" is a claim.
 *
 * ## `null` spend is not `$0.0000`
 *
 * A pre-#2b artifact did not record judge spend. Rendering `$0.0000` there says
 * the run was free, which is the specific lie `Flatline` exists to prevent.
 */
export function CostChip({
  judgeUsd,
  packName,
}: {
  judgeUsd: number | null;
  packName: string | null;
}) {
  // The allowlist cannot change while the server is running, so asking twice is
  // pure noise.
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: () => apiGet<PackListPage>("/packs"),
    staleTime: Infinity,
  });
  const pack =
    packName === null
      ? undefined
      : packs.data?.items.find((row) => row.name === packName);

  const axes = useQuery({
    queryKey: ["pack-axes", pack?.id ?? null],
    enabled: pack !== undefined,
    queryFn: () =>
      apiGet<PackAxes>(`/packs/${encodeURIComponent(pack!.id)}/axes`),
    staleTime: Infinity,
  });

  const ceiling = axes.data?.max_usd_per_run ?? null;
  const settled =
    packName === null ||
    packs.isError ||
    (packs.isSuccess && pack === undefined) ||
    axes.isError ||
    axes.isSuccess;
  const state: "known" | "unknown" | "pending" = !settled
    ? "pending"
    : ceiling === null
      ? "unknown"
      : "known";

  const share =
    state === "known" && ceiling !== null && ceiling > 0 && judgeUsd !== null
      ? `${((judgeUsd / ceiling) * 100).toFixed(1)}% used`
      : null;

  return (
    <span
      data-testid="cost-chip"
      data-ceiling={state}
      className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
    >
      {judgeUsd === null ? (
        <Flatline word="unrecorded" reason="judge spend was not recorded" />
      ) : (
        <span
          data-metric="judge_usd"
          data-numeric="judge_usd"
          className="text-readout tabular-nums text-chassis-900"
        >
          {formatUsd(judgeUsd)}
        </span>
      )}
      {state === "pending" ? (
        <span className="text-legend text-chassis-600">
          reading the pack ceiling…
        </span>
      ) : state === "unknown" ? (
        <span
          className="text-legend text-chassis-600"
          title={
            packName === null
              ? "this artifact did not record a pack name"
              : `the pack ${packName} is not on this server's --target allowlist, so its per-run ceiling cannot be read`
          }
        >
          pack ceiling unknown
        </span>
      ) : (
        <span className="text-legend text-chassis-600">
          <span className="tabular-nums">{`of ${formatUsd(ceiling!)}`}</span>
          {` pack ceiling${share === null ? "" : ` · ${share}`}`}
        </span>
      )}
    </span>
  );
}
