import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ControlButtons } from "../ControlButtons";
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

/** Every `class` attribute in the subtree, SVG elements included. */
function classesIn(root: Element): string[] {
  return [...root.querySelectorAll("*")].flatMap((node) => {
    const value = node.getAttribute("class");
    return value === null ? [] : [value];
  });
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

  it("shows the exit code only once there is one", () => {
    const view = render(<LiveBanner state={stateWith({ phase: "running" })} />);
    expect(screen.getByTestId("live-window").textContent).not.toContain(
      "Exit code",
    );
    view.unmount();

    render(
      <LiveBanner state={stateWith({ phase: "finished", exitCode: 3 })} />,
    );
    const window = screen.getByTestId("live-window");
    expect(window.textContent).toContain("Exit code");
    expect(window.querySelector('[data-numeric="exit_code"]')?.textContent).toBe(
      "3",
    );
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

  /**
   * The guard the contrast test cannot be (ruling R4-24).
   *
   * On this ground chassis-600 measures 2.92:1, chassis-500 4.33:1 and every
   * status hue is below AA — `status-passed`, the best of them, is 3.60:1. The
   * contrast guard measures each of those files against `chassis-25` and
   * certifies them, so dropping `CostChip`, `Flatline`, `RunStatusChip` or
   * `VerdictBadge` in here would ship unreadable text with a green suite.
   */
  it("puts no pale-chassis ink on the dark ground", () => {
    render(
      <LiveBanner state={stateWith({ phase: "running" })}>
        <ControlButtons
          phase="running"
          requested={null}
          error="a refusal, so the alarm ink is on screen too"
          onAction={() => {}}
        />
      </LiveBanner>,
    );

    const offending = classesIn(screen.getByTestId("live-window")).filter(
      (value) => /\btext-(chassis-(500|600|700|800|900)|status-|degraded)/.test(value),
    );
    expect(
      offending,
      "these inks were measured against the pale face and fail on the inset window",
    ).toEqual([]);
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
