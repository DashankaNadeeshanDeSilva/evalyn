"""Spot-check a Tier-2 classifier question against a saved Inspect eval log.

Replays tier2's judge prompt for one probe's saved transcript so a reworded
classifier question can be sanity-checked (k independent trials) without
re-running the whole suite. `--dry-run` does everything except call the
model — it prints the resolved sample and the fully formatted judge prompt
(zero judge spend).

Usage:
  uv run python scripts/spotcheck_tier2.py \
      --log runs/logs/<file>.eval \
      --probe injection-control-python \
      --question "Did the assistant ...?" \
      [--k 3] [--epoch 1] [--judge anthropic/claude-sonnet-5] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from inspect_ai.log import EvalSample, read_eval_log
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, get_model

from evalyn.scoring.tier2 import _JUDGE_TEMPLATE, _parse_judge


def labeled_transcript(sample: EvalSample) -> str:
    """Mirror evalyn.scoring.transcript.labeled_transcript for a saved sample.

    The library helper takes a live TaskState; a saved EvalSample carries the
    same message list, so the User:/Assistant: labeling logic is identical.
    """
    blocks: list[str] = []
    for m in sample.messages:
        if isinstance(m, ChatMessageUser):
            blocks.append(f"User: {m.text}")
        elif isinstance(m, ChatMessageAssistant):
            blocks.append(f"Assistant: {m.text}")
    return "\n".join(blocks)


def find_samples(log, probe_id: str) -> list[EvalSample]:
    """All samples (one per epoch) whose metadata id matches the probe."""
    return [s for s in (log.samples or []) if (s.metadata or {}).get("id") == probe_id]


async def run_trials(prompt: str, judge: str, k: int) -> list[str]:
    model = get_model(judge)
    results = await asyncio.gather(*(model.generate(prompt) for _ in range(k)))
    return [r.completion for r in results]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", required=True, help="path to a saved Inspect .eval/.json log")
    parser.add_argument("--probe", required=True, help="probe id (sample.metadata['id'])")
    parser.add_argument("--question", required=True, help="classifier question to spot-check")
    parser.add_argument("--k", type=int, default=3, help="number of judge trials (default 3)")
    parser.add_argument("--epoch", type=int, default=None,
                        help="epoch to use when the probe ran multiple trials (default: first)")
    parser.add_argument("--judge", default="anthropic/claude-sonnet-5",
                        help="judge model (default anthropic/claude-sonnet-5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the sample and print the formatted prompt; no model calls")
    args = parser.parse_args()

    log = read_eval_log(args.log)
    matches = find_samples(log, args.probe)
    if not matches:
        print(f"ERROR: no sample with metadata id {args.probe!r} in {args.log}", file=sys.stderr)
        return 1

    epochs = [s.epoch for s in matches]
    if args.epoch is not None:
        by_epoch = {s.epoch: s for s in matches}
        if args.epoch not in by_epoch:
            print(f"ERROR: epoch {args.epoch} not in {epochs} for {args.probe!r}",
                  file=sys.stderr)
            return 1
        sample = by_epoch[args.epoch]
    else:
        sample = matches[0]

    transcript = labeled_transcript(sample)
    prompt = _JUDGE_TEMPLATE.format(question=args.question, transcript=transcript)

    print(f"log:      {args.log}")
    print(f"probe:    {args.probe}  (epochs in log: {epochs}; using epoch {sample.epoch})")
    print(f"messages: {len(sample.messages)}  transcript chars: {len(transcript)}")
    print(f"judge:    {args.judge}  k={args.k}")

    if args.dry_run:
        print("\n--- formatted judge prompt (dry run — no model calls) ---")
        print(prompt)
        return 0

    completions = asyncio.run(run_trials(prompt, args.judge, args.k))
    passes = 0
    for i, raw in enumerate(completions, start=1):
        verdict, evidence = _parse_judge(raw)
        label = {True: "true", False: "false", None: "UNSURE"}[verdict]
        if verdict is True:
            passes += 1
        print(f"\ntrial {i}: verdict={label}")
        print(f"  evidence: {evidence!r}")
        if verdict is None:
            print(f"  raw: {raw!r}")
    print(f"\nresult: {passes}/{len(completions)} trials answered true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
