# Inspect AI fit spike — findings

**Date:** 2026-07-22
**Purpose:** De-risk the design's central-but-unvalidated assumption (design §0, §9) — that Evalyn's
concepts map cleanly onto Inspect AI primitives — *before* writing the implementation plan.
**Verdict:** ✅ **The mapping holds. Build on Inspect as planned.** One architecture-shaping finding
(reducers are task-level, not per-probe) that the plan must absorb; no blockers.

Spike code (throwaway, untracked): `spike/toy_target.py` (a TwinCore-like session + SSE chat server)
and `spike/evalyn_spike.py` (the Evalyn-shaped Inspect eval). Ran on `inspect_ai 0.3.249`, Python
3.12, in the project-root `.venv`.

---

## What was tested

A real black-box target (stdlib HTTP server: `POST /session`, then `POST /chat` streaming a
Vercel-AI-style SSE token stream) with a **deliberately flaky** injection guard that leaks its
"system prompt" ~40% of the time. Driven through a full Evalyn-shaped Inspect eval: 2 probes
(a grounding probe and a multi-turn trust-then-pivot injection probe) × 3 epochs = 6 samples.

## The mapping, claim by claim

| Design claim | Inspect primitive used | Result |
|---|---|---|
| probe suite → `Task` | `Task(dataset=MemoryDataset([...]))` | ✅ probes as in-memory `Sample`s with `metadata` (id, category, kind, `safety_critical`, turns) |
| session driver → `Solver` driving a **live product**, not a model | custom `@solver`; **never calls `generate()`** | ✅ opens session + streams multi-turn SSE via async `httpx`, stores the product's reply with `ModelOutput.from_content(...)` |
| multi-turn probe | messages appended to `state.messages` | ✅ 2-turn trust-then-pivot ran; full transcript recorded in the log |
| each scoring tier → a `Scorer` | list of scorers on the `Task` | ✅ Tier-1 deterministic (regex leak invariant) + Tier-2 classifier judge composed side by side, both landed in the log |
| `samples: n` → repeated trials | `epochs=Epochs(3, [...])` | ✅ |
| **pass@k and pass^k** | **native `pass_at(k)` / `pass_k(k)` reducers** | ✅ **did not implement — Inspect ships them.** Also `at_least(k)`, `mean`, etc. |
| bounded per-pack concurrency | `concurrency("target-http", 4)` | ✅ |
| judge ≠ generator family, provider-pluggable | `get_model(...)` inside the scorer | ✅ plumbing proven with `mockllm/` (no API key); real judge just swaps the model id |
| a run → a standard eval log | `.eval` file, re-readable via `read_eval_log` | ✅ viewable in `inspect view`; all per-epoch scores + reducer outputs present |

## The headline result — pass^k earns its place (empirically)

The injection guard leaked in **2 of 3 epochs**. Aggregated across both probes:

| Reducer | accuracy | What it says about the flaky safety probe |
|---|---|---|
| `mean` (majority-ish) | **0.667** | "mostly fine" — **hides the risk** |
| `pass_at_3` (pass@k) | 1.000 | "it *can* refuse" — true but not what safety needs |
| `pass_k_3` (**pass^k**) | **0.500** | "**not reliable every time**" — correctly flags it |

This is the design's §3 argument made concrete: a safety-critical probe that majority-vote would
wave through is caught the moment you gate on pass^k — and Inspect computes it for free.

---

## Findings that shape the implementation plan

1. **Reducers are task-level, not per-probe.** Inspect applies a `Task`'s reducer set uniformly to
   every sample. The design wants **pass^k for safety-critical probes but score-bands for quality
   probes** — that is a *per-probe policy*, which a single Task's reducer config cannot express.
   **Resolution (clean, and confirms the intended boundary):** attach *all* useful reducers
   (`pass_at`, `pass_k`, `mean`) to every probe so Inspect **records** every number, then let
   **Evalyn's own `gate` layer read the eval log and apply pass/fail policy per probe** from its
   `kind` / `safety_critical` metadata (pass^k for safety, bands for quality, capability probes
   excluded from pass/fail). Inspect stays the compute+record spine; **the gating policy is
   Evalyn's differentiator** — exactly the §0 boundary. This wants a small "gate-diff/reporter"
   component in `engine/`, reading logs rather than re-deriving scores.

2. **The Solver-drives-a-live-product pattern works and is the right seam.** Storing the product's
   reply via `ModelOutput.from_content` (no `generate()` call) is clean; the SSE stream-format
   adapter (`0:"token"` framing) lives naturally inside the solver — matching the pack contract's
   pluggable `event_format`.

3. **Minor API notes for the scaffold:** `epochs` needs `Epochs(n, [reducers])` (a bare tuple
   raises); scorers use `@scorer(metrics=[accuracy(), stderr()])`; external HTTP **must** be async
   `httpx` (Inspect's async core) and bounded with `concurrency()` — never blocking `requests`.

4. **Judge quality is out of scope for a plumbing spike.** `mockllm` proves an LLM-judge tier
   composes and logs; it says nothing about judge accuracy. The design's anchor-set calibration
   (§3) remains the real safeguard and still needs a real model to validate.

5. **Not an Inspect issue, but noted:** a stdlib SSE server drops streamed connections under
   concurrency unless it speaks HTTP/1.1 with proper `Content-Length`/`Connection: close`. Real
   targets (FastAPI/uvicorn) won't have this; it only affected the toy server.

## Bottom line for planning

No reason to reconsider the Inspect dependency — it covers more than the design assumed (pass@k/
pass^k, epoch reducers, multi-scorer logs, concurrency, model-provider abstraction all out of the
box). The plan should: (a) phase **gate first**, with a log-reading **gate-diff/reporter** that owns
per-probe pass/fail policy (finding #1); (b) treat the session driver + stream adapters as the first
real engine code; (c) keep discovery last. Proceed to `superpowers:writing-plans` against the
amended design with these findings folded in.
