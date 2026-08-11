import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ControlButtons } from "../ControlButtons";
import { IconAlert, IconCheck, IconQuery } from "../InstrumentIcon";
import { LiveBanner } from "../LiveBanner";
import {
  initialRunEventsState,
  type RunEventsState,
} from "../../hooks/useRunEvents";

/**
 * The one inset window, and the controls inside it.
 *
 * Both are presentational on purpose: jsdom has no `EventSource`, so keeping
 * the fold and the socket out of these components is what makes the region
 * testable at all. `LiveRunPanel.test.tsx` covers the seam that joins them.
 *
 * The last test in the first block is the one that would not exist without
 * ruling R4-24: the contrast guard reasons per file, so a component written
 * against the pale chassis and dropped in here passes it while being
 * unreadable. That test is a structural stand-in for the measurement the guard
 * cannot make.
 */

function stateWith(patch: Partial<RunEventsState>): RunEventsState {
  return { ...initialRunEventsState, ...patch };
}

/**
 * The shapes a mark is drawn from, joined — the family shares one viewBox,
 * stroke and colour, and carries no identity attribute, so the geometry is the
 * only thing that tells one glyph from another.
 */
function shapesOf(root: Element | null): string {
  if (root === null) return "";
  const svg = root.tagName.toLowerCase() === "svg" ? root : root.querySelector("svg");
  return [...(svg?.querySelectorAll("path, circle") ?? [])]
    .map((node) => node.getAttribute("d") ?? node.outerHTML)
    .join("|");
}

/** The same, for a mark rendered on its own, so one can be named as a reference. */
function shapesOfElement(element: ReactElement): string {
  const view = render(<div data-testid="mark-reference">{element}</div>);
  const shapes = shapesOf(screen.getByTestId("mark-reference"));
  view.unmount();
  return shapes;
}

describe("the live readout window", () => {
  it("says the phase with a glyph and a word, never a colour alone", () => {
    for (const [phase, word] of [
      ["running", "live"],
      ["paused", "paused"],
      ["cancelling", "cancelling"],
      ["finished", "finished"],
    ] as const) {
      const view = render(<LiveBanner state={stateWith({ phase })} />);
      const readout = screen.getByTestId("live-phase");
      expect(readout.textContent?.toLowerCase()).toContain(word);
      expect(
        readout.querySelector("svg"),
        `the ${phase} phase renders without a mark`,
      ).not.toBeNull();
      view.unmount();
    }
  });

  it("flat-lines an unreported spend instead of reading it as free", () => {
    render(<LiveBanner state={stateWith({ phase: "running" })} />);

    const window = screen.getByTestId("live-window");
    expect(window.textContent).toContain("not reported yet");
    // `null` is not zero. A live window that says $0.0000 tells an operator
    // deciding whether to stop paying that the run has cost them nothing.
    expect(window.textContent).not.toContain("$0.0000");
  });

  it("counts the probes it actually has, never a separate counter", () => {
    render(
      <LiveBanner
        state={stateWith({
          phase: "running",
          probes: [
            { probeId: "a", passK: 1 },
            { probeId: "b", passK: 0 },
            { probeId: "c", passK: null },
          ],
          judgeUsd: 0.0138,
          trials: 9,
        })}
      />,
    );

    const window = screen.getByTestId("live-window");
    expect(
      window.querySelector('[data-numeric="probes_scored"]')?.textContent,
    ).toBe("3");
    expect(window.querySelector('[data-numeric="trials"]')?.textContent).toBe(
      "9",
    );
    expect(window.querySelector('[data-numeric="judge_usd"]')?.textContent).toBe(
      "$0.0138",
    );
    // Tabular figures on every numeric, so a column does not jitter between
    // renders while the run is moving.
    for (const cell of window.querySelectorAll("[data-numeric]")) {
      expect(cell.getAttribute("class")).toContain("tabular-nums");
    }
  });

  /**
   * The wiring pass's demo bug, pinned.
   *
   * `run.finished` carries `status`, never `exit_code` — the exit code is the
   * CLI's, decided after the artifact is written. The window read one anyway,
   * so a clean run rendered "EXIT CODE not reported" forty pixels above a gate
   * block rendering "EXIT CODE 1": two contradictory statements, one screenful
   * apart, on the projector.
   */
  it("reports the outcome the stream carries, and never an exit code it does not", () => {
    const view = render(<LiveBanner state={stateWith({ phase: "running" })} />);
    // Nothing has ended, so there is no outcome to state.
    expect(screen.queryByTestId("live-outcome")).toBeNull();
    view.unmount();

    render(
      <LiveBanner
        state={stateWith({ phase: "finished", finishStatus: "ok" })}
      />,
    );
    const window = screen.getByTestId("live-window");
    expect(screen.getByTestId("live-outcome").textContent).toContain(
      "completed",
    );
    // The exit code is not this window's to report, in any rendition.
    expect(window.textContent?.toLowerCase()).not.toContain("exit code");
    // And a run that told us how it ended is not an unreported anything. (The
    // spend reading's own "not reported yet" is a different, honest, absence.)
    expect(screen.getByTestId("live-outcome").textContent).not.toContain(
      "not reported",
    );
  });

  it("says a run that did not complete did not complete, and says nothing when the stream did not say", () => {
    const errored = render(
      <LiveBanner
        state={stateWith({ phase: "finished", finishStatus: "error" })}
      />,
    );
    expect(screen.getByTestId("live-outcome").textContent).toContain(
      "did not complete",
    );
    errored.unmount();

    render(
      <LiveBanner
        state={stateWith({ phase: "finished", finishStatus: null })}
      />,
    );
    // Absent is unreported, never "failed": a status the stream never sent is
    // not a run that went wrong.
    expect(screen.getByTestId("live-outcome").textContent).toContain(
      "not reported",
    );
  });

  /**
   * The alarm was the visible half of the original bug: with no exit code on
   * the wire, `exitCode === 0` was false for every run that ever finished, so
   * **every** finished run drew the alarm glyph.
   *
   * The mark that replaced it carries **valence and nothing else** — the alarm
   * for a run that did not complete, the unresolved mark for every other
   * ending. It deliberately does not distinguish `"ok"` from an unreported
   * status: that distinction is the outcome *word* below, and a mark that drew
   * it would be a second verdict on a screen that already has one. Marks are
   * compared by the shapes they are drawn from, since the family carries no
   * identity attribute.
   */
  it("marks a run that did not complete with the alarm, and every other ending neutrally", () => {
    const alarm = shapesOfElement(<IconAlert />);
    const unresolved = shapesOfElement(<IconQuery />);
    expect(alarm).not.toBe(unresolved);

    for (const [status, expected] of [
      ["ok", unresolved],
      [null, unresolved],
      ["error", alarm],
    ] as const) {
      const view = render(
        <LiveBanner
          state={stateWith({ phase: "finished", finishStatus: status })}
        />,
      );
      expect(
        shapesOf(screen.getByTestId("live-phase").querySelector("svg")),
        `a run that finished with status ${String(status)} carries the wrong mark`,
      ).toBe(expected);
      // Every rendition still says "finished": the verdict is the gate banner's
      // job, and a cross here would claim a gate failure for a cancelled run.
      expect(screen.getByTestId("live-phase").textContent).toContain("finished");
      view.unmount();
    }
  });

  it("says frames were lost rather than reporting a thinner run", () => {
    render(
      <LiveBanner
        state={stateWith({
          phase: "running",
          connection: "reconnecting",
          missedEvents: 4,
        })}
      />,
    );

    const notice = screen.getByTestId("live-connection");
    expect(notice.textContent).toContain("Reconnecting");
    expect(notice.textContent).toContain("4 events lost");
    expect(notice.querySelector("svg")).not.toBeNull();
  });

  it("names the problem and the recovery when the stream gives up", () => {
    render(
      <LiveBanner
        state={stateWith({ phase: "running", connection: "closed" })}
      />,
    );

    const notice = screen.getByTestId("live-connection");
    expect(notice.textContent).toContain("stopped updating");
    // The recovery, and the reassurance that the run is not what broke.
    expect(notice.textContent).toContain("reload the page");
    expect(notice.textContent).toContain("run itself is unaffected");
  });

  it("states the pack ceiling beside the spend, and says so when it has none", () => {
    const view = render(
      <LiveBanner
        state={stateWith({ phase: "running", judgeUsd: 0.5 })}
        ceiling={2}
        ceilingSettled
      />,
    );
    // `$0.5000` means nothing until you know the ceiling is $2 and not 2 cents,
    // and this is the readout an operator decides to cancel from.
    expect(screen.getByTestId("live-window").textContent).toContain("of $2.0000");
    expect(screen.getByTestId("live-window").textContent).toContain("25.0% used");
    view.unmount();

    const unknown = render(
      <LiveBanner
        state={stateWith({ phase: "running", judgeUsd: 0.5 })}
        ceiling={null}
        ceilingSettled
      />,
    );
    // Never a default: the run's pack may not be on this server's allowlist.
    expect(screen.getByTestId("live-window").textContent).toContain(
      "pack ceiling unknown",
    );
    unknown.unmount();

    render(
      <LiveBanner state={stateWith({ phase: "running", judgeUsd: 0.5 })} />,
    );
    // Still reading is not the same claim as "there is no ceiling".
    expect(screen.getByTestId("live-window").textContent).not.toContain(
      "ceiling",
    );
  });
});

/**
 * The guard the contrast test cannot be (ruling R4-24), applied to **every
 * state the window can actually be in**.
 *
 * The first version of this rendered one state — `running`, no gap, no
 * outcome, resting controls — and scanned `text-` only. Review reproduced the
 * consequence: a `<Flatline>` inserted into the **terminal** branch left the
 * whole suite green, because that branch renders only when a run has finished.
 * A control that fires in one of eleven states is not a control.
 *
 * So the inventory below is an **allowlist**, not a denylist, and every state
 * is rendered against it. Adding a token to it means measuring it first:
 *
 *   text-inset-ink                     15.21:1  readings, alarms, key labels
 *   text-chassis-400                    7.58:1  legends and secondary prose
 *   bg-inset                                    the window's own ground
 *   bg-safety                           6.44:1  the orange key's edge (1.4.11)
 *   text-safety-ink                     6.05:1  on the orange it always sits on
 *   outline-safety-ink                  6.05:1  that key's hover edge
 *   [--rule:theme(colors.chassis.400)]  7.58:1  a secondary key's engraved edge
 *   [--rule:theme(colors.inset.ink)]   15.21:1  the same edge, hovered
 *
 * Everything else in the palette is refused here, and the refusals are the
 * point: chassis-600 — the pale face's own secondary prose — measures 2.92:1,
 * chassis-500 4.33:1, and every status hue is below AA (status-passed, the best
 * of them, is 3.60:1). The per-file contrast guard measures each of those files
 * against `chassis-25` and certifies them, so `Flatline`, `CostChip`,
 * `RunStatusChip` or `VerdictBadge` dropped in here would ship unreadable text
 * with a green suite and a passing guard.
 */
const MEASURED_ON_THE_INSET_GROUND = new Set([
  "text-inset-ink",
  "text-chassis-400",
  "bg-inset",
  "bg-safety",
  "text-safety-ink",
  "outline-safety-ink",
  "[--rule:theme(colors.chassis.400)]",
  "[--rule:theme(colors.inset.ink)]",
]);

/** Anything naming a palette family, in any utility and behind any variant. */
const PALETTE = /(chassis|inset|safety|status|degraded)/;

/**
 * Every colour-bearing class in the subtree, variants stripped.
 *
 * Not `text-` and `bg-` only: this codebase identifies **every control edge**
 * with `[--rule:theme(...)]` and the safety key's hover edge with an outline,
 * and both were invisible to the first version of this check.
 */
function unmeasuredInk(root: Element): string[] {
  const found = new Set<string>();
  for (const node of [root, ...root.querySelectorAll("*")]) {
    const value = node.getAttribute("class");
    if (value === null) continue;
    for (const raw of value.split(/\s+/)) {
      // `hover:[--rule:theme(...)]` -> `[--rule:theme(...)]`. The arbitrary
      // value's own colons are safe: they sit inside brackets, which the
      // variant pattern cannot cross.
      const token = raw.replace(/^(?:[a-z-]+:)+(?=\[|[a-z])/, "");
      if (token === "" || !PALETTE.test(token)) continue;
      if (!MEASURED_ON_THE_INSET_GROUND.has(token)) found.add(token);
    }
  }
  return [...found].sort();
}

function expectMeasured(where: string) {
  expect(
    unmeasuredInk(screen.getByTestId("live-window")),
    `${where}: this ink has never been measured against the inset window`,
  ).toEqual([]);
}

const WINDOW_STATES: [string, RunEventsState][] = [
  ["connecting", stateWith({ phase: "connecting" })],
  ["running", stateWith({ phase: "running", judgeUsd: 0.0138, trials: 2 })],
  ["running with no spend reported", stateWith({ phase: "running" })],
  ["paused", stateWith({ phase: "paused", judgeUsd: 0.5 })],
  ["cancelling", stateWith({ phase: "cancelling" })],
  [
    "finished, completed",
    stateWith({ phase: "finished", finishStatus: "ok" }),
  ],
  [
    "finished, did not complete",
    stateWith({ phase: "finished", finishStatus: "error" }),
  ],
  [
    "finished with no status reported",
    stateWith({ phase: "finished", finishStatus: null, connection: "closed" }),
  ],
  [
    "reconnecting after a gap",
    stateWith({ phase: "running", connection: "reconnecting", missedEvents: 4 }),
  ],
  [
    "recovered, but events were lost",
    stateWith({ phase: "running", connection: "open", missedEvents: 2 }),
  ],
  [
    "stalled before the run finished",
    stateWith({ phase: "running", connection: "closed" }),
  ],
];

/**
 * One glyph, one meaning, across the **whole surface** — not merely within one
 * component, which is where the first version of this reasoned.
 *
 * `IconCheck` is the gate banner's "gate passed" mark, in the pass colour, at
 * the largest type on the run detail page. The live window sits directly above
 * that banner, and in the demo case the two are on screen together: a run that
 * completed cleanly whose gate went red. A check up here over a cross down
 * there is one screen disagreeing with itself at projector distance, whatever
 * the two marks each mean in their own file.
 *
 * So the window renders the check in **no** state it can be in. It is an
 * allowlist-style check over every state the ink guard already enumerates,
 * because the branch that draws a mark for a finished run is one of eleven and
 * a spot check would not reach it.
 */
describe("the gate's check mark belongs to the gate banner alone", () => {
  it.each(WINDOW_STATES)("the window draws no check, %s", (name, state) => {
    const check = shapesOfElement(<IconCheck />);
    render(<LiveBanner state={state} />);

    const drawn = [
      ...screen.getByTestId("live-window").querySelectorAll("svg"),
    ].map((svg) => shapesOf(svg));
    expect(drawn.length, `${name}: the window drew no mark at all`).toBeGreaterThan(0);
    expect(
      drawn,
      `${name}: this window drew the gate's own pass mark, which sits 40px below it`,
    ).not.toContain(check);
  });
});

type ControlProps = Parameters<typeof ControlButtons>[0];

const CONTROL_STATES: [string, ControlProps][] = [
  [
    "resting keys",
    { phase: "running", requested: null, error: null, onAction: () => {} },
  ],
  [
    "resume in place of pause",
    { phase: "paused", requested: null, error: null, onAction: () => {} },
  ],
  [
    "waiting on an acknowledgement",
    { phase: "running", requested: "cancel", error: null, onAction: () => {} },
  ],
  [
    "winding down after a cancel ack",
    { phase: "cancelling", requested: null, error: null, onAction: () => {} },
  ],
  [
    "nothing heard from the run yet",
    { phase: "connecting", requested: null, error: "refused", onAction: () => {} },
  ],
  [
    "a refused control request",
    {
      phase: "running",
      requested: null,
      error: "cancel refused — busy",
      onAction: () => {},
    },
  ],
];

describe("every ink the dark window can render was measured against it", () => {
  it.each(WINDOW_STATES)("the window, %s", (name, state) => {
    render(<LiveBanner state={state} />);
    expectMeasured(name);
  });

  it.each([
    ["a ceiling to compare against", 2 as number | null],
    ["no ceiling available", null as number | null],
  ])("the window, spend with %s", (name, ceiling) => {
    render(
      <LiveBanner
        state={stateWith({ phase: "running", judgeUsd: 0.5 })}
        ceiling={ceiling}
        ceilingSettled
      />,
    );
    expectMeasured(name);
  });

  it.each(CONTROL_STATES)("the controls, %s", (name, props) => {
    render(
      <LiveBanner state={stateWith({ phase: props.phase })}>
        <ControlButtons {...props} />
      </LiveBanner>,
    );
    expectMeasured(name);
  });

  it("the controls, armed for a cancel", async () => {
    const user = userEvent.setup();
    render(
      <LiveBanner state={stateWith({ phase: "running" })}>
        <ControlButtons
          phase="running"
          requested={null}
          error={null}
          onAction={() => {}}
        />
      </LiveBanner>,
    );

    await user.click(screen.getByRole("button", { name: /Cancel run/ }));
    expect(screen.getByTestId("cancel-confirm")).toBeInTheDocument();
    expectMeasured("armed for a cancel");
  });

  it("the controls, the orange key hovered", async () => {
    const user = userEvent.setup();
    render(
      <LiveBanner state={stateWith({ phase: "running" })}>
        <ControlButtons
          phase="running"
          requested={null}
          error={null}
          onAction={() => {}}
        />
      </LiveBanner>,
    );

    await user.hover(screen.getByTestId("safety-key"));
    expectMeasured("the orange key hovered");
  });

  /**
   * The control's own discriminating red, kept as a test rather than a claim:
   * the scanner must reject an ink that is genuinely wrong here. `chassis-600`
   * is the exact ink `Flatline` and `CostChip` carry, at 2.92:1 on this ground.
   */
  it("rejects an ink that was measured against the pale face", () => {
    render(
      <LiveBanner state={stateWith({ phase: "running" })}>
        <span className="text-chassis-600">unrecorded</span>
      </LiveBanner>,
    );

    expect(unmeasuredInk(screen.getByTestId("live-window"))).toEqual([
      "text-chassis-600",
    ]);
  });
});

describe("the run controls", () => {
  it("says on the key itself that pausing does not stop spend", async () => {
    render(
      <ControlButtons
        phase="running"
        requested={null}
        error={null}
        onAction={() => {}}
      />,
    );

    // Fixed by ruling R4-12, word for word: pause starts no new samples, but
    // trials already in flight finish and keep billing.
    const pause = screen.getByRole("button", {
      name: /Pause \(finishes in-flight trials\)/,
    });
    expect(pause.textContent).toContain("Pause (finishes in-flight trials)");
    expect(pause.textContent).toContain("keep spending");
  });

  it("offers resume in place of pause once the engine has acknowledged a pause", () => {
    render(
      <ControlButtons
        phase="paused"
        requested={null}
        error={null}
        onAction={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /Resume/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pause/ })).toBeNull();
  });

  it("makes cancel confirm, and states what cancelling actually costs", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <ControlButtons
        phase="running"
        requested={null}
        error={null}
        onAction={onAction}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Cancel run/ }));

    const confirm = screen.getByTestId("cancel-confirm");
    expect(confirm.textContent).toContain("keep spending");
    // Arming is not acting: nothing has been requested yet.
    expect(onAction).not.toHaveBeenCalled();

    await user.click(
      within(confirm).getByRole("button", { name: /Cancel run/ }),
    );
    expect(onAction).toHaveBeenCalledWith("cancel");
  });

  it("lets the operator back out of the confirmation", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(
      <ControlButtons
        phase="running"
        requested={null}
        error={null}
        onAction={onAction}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Cancel run/ }));
    await user.click(screen.getByRole("button", { name: /Keep running/ }));

    expect(screen.queryByTestId("cancel-confirm")).toBeNull();
    expect(onAction).not.toHaveBeenCalled();
  });

  /**
   * The 202 is not the acknowledgement. `accepted: true` says the control file
   * was written; the matching `control.*` event is what says the engine took
   * it. A UI that flipped to "paused" here would be claiming something that may
   * not happen for another minute — or, if the engine never acknowledges, ever.
   */
  it("waits for the engine rather than believing its own request", () => {
    render(
      <ControlButtons
        phase="running"
        requested="pause"
        error={null}
        onAction={() => {}}
      />,
    );

    const waiting = screen.getByTestId("control-waiting");
    expect(waiting.textContent).toContain("waiting for the engine to acknowledge");
    // The phase is still `running`, and nothing on screen claims otherwise.
    expect(screen.queryByRole("button", { name: /Pause/ })).toBeNull();
  });

  it("offers no controls at all once the run has ended", () => {
    const { container } = render(
      <ControlButtons
        phase="finished"
        requested={null}
        error={null}
        onAction={() => {}}
      />,
    );

    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("shows a refused control request with a glyph, not colour alone", () => {
    render(
      <ControlButtons
        phase="running"
        requested={null}
        error="cancel refused — busy: another run holds the control channel"
        onAction={() => {}}
      />,
    );

    const alarm = screen.getByTestId("control-error");
    expect(alarm.textContent).toContain("cancel refused");
    expect(alarm.querySelector("svg")).not.toBeNull();
  });
});
