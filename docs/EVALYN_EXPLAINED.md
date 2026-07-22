# Evalyn, explained in plain English

**What this doc is:** a friendly, jargon-light tour of the whole project — from the big picture
down to the important details. If you only read one file to understand *what we're building and
why*, read this one. (The precise, technical version lives in
[`2026-07-21-evalyn-design.md`](./2026-07-21-evalyn-design.md); the build steps live in
[`superpowers/plans/`](./superpowers/plans/).)

---

## 1. The one-sentence version

**Evalyn is a tool that tests an AI chat product** — the way you'd test any software before
shipping it, except the thing being tested is an AI that *talks*, which makes it slippery to test.

## 2. The problem it solves

When you build a normal app, you write tests: "if I click this, that should happen." If a change
breaks something, a test goes red and you know instantly.

AI products don't work like that. The AI gives *different wording every time*, it can be subtly
wrong, it can be talked into misbehaving, and "good answer vs bad answer" is often a judgment call.
So teams building AI products often **fly blind**: they change a prompt or swap a model, something
feels worse, and they have no way to know for sure except waiting for users to complain.

Evalyn's job is to replace "guess and hope" with "measure and know."

## 3. The three ways Evalyn tests (the heart of it)

Evalyn does its job through **three modes**. Same tool, three ways to use it:

### 🚦 `gate` — "Did I break anything?"
A fixed set of tests you run every time you change something. Like a **smoke alarm**: it doesn't
find *new* dangers, but if a known one shows up, it goes off loudly and clearly. Fast, repeatable,
gives a clean **pass/fail** you can wire into your automated pipeline so a bad change gets caught
*before* it ships.

### ⚖️ `compare` — "Which version is actually better?"
Put two versions of your AI side by side (say, before and after a prompt tweak) and let Evalyn
judge which one answers better. Like a **blind taste test**: the judge doesn't know which is which,
and the order is shuffled, so the verdict is honest. Use it to decide whether a change is *really*
an improvement before you adopt it.

### 🔍 `discover` — "What problems don't I know about yet?"
A curious, slightly mischievous AI tester that pokes at your product trying to *find failures you
never thought to test for* — like hiring a clever tester whose whole job is to break things in
creative ways. It doesn't follow a script; it notices "hmm, it got evasive when I mentioned
salary" and *chases that thread*.

**How they relate:** `gate` guards against known problems, `compare` helps you improve, and
`discover` finds the unknown problems — which then *become* new `gate` tests (more on that in §8).

## 4. The big idea that makes Evalyn reusable

Evalyn is built in **two layers**, and keeping them separate is the whole trick:

- **The engine** — the generic machinery. It knows *how* to run tests, talk to a chat product,
  grade answers, and report results. It knows **nothing** about any specific product.
- **The target pack** — a folder of files that describes *one specific product*: its web address,
  how to start a chat, and the actual tests that matter for it.

**Analogy: a universal TV remote.** The remote (engine) works with any TV. You just load the right
profile (target pack) for *your* TV. Want to test a different product? Write a new pack — you never
touch the engine.

**The catch nobody can remove:** the *tests themselves* — what counts as a good vs bad answer for
*your* product — are always yours to write. No tool can decide that for you, because it's the whole
point of *your* product. Evalyn makes the machinery free and reusable; it can't make "the
definition of good" reusable. What it *can* do is make writing that definition as painless as
possible.

## 5. How Evalyn grades an answer (the trust ladder)

The scariest part of testing an AI is: **how do you trust the grade?** An AI grading another AI can
be wrong, biased, or just make things up. So Evalyn grades in **tiers, cheapest and most trustworthy
first**, and only climbs the ladder when it has to:

1. **Tier 1 — plain rules (free, exact).** Simple factual checks: "Is the reply empty?" "Did it leak
   an internal secret?" "Does it contain the required word?" These are *facts, not opinions* — if one
   fails, that alone can fail the test. No AI involved.

2. **Tier 2 — a small, cheap AI judge.** For yes/no questions with a right answer that rules can't
   easily catch: "Did the assistant *refuse* the trick request?" The judge must **quote the exact
   words** from the reply that justify its verdict — if it can't point to real evidence, its answer
   is thrown out rather than trusted. This kills the "the AI just made it up" problem.

3. **Tier 3 — a strong AI judge for nuance.** For fuzzy qualities like tone, completeness, or
   staying in character. To keep it honest, the judge first writes down *its own grading steps* from
   a fixed rubric, then grades against them (more stable than a vague "rate this 1–5").

**And we grade the grader.** We keep a small set of examples that a *human* has scored by hand. Any
time we change the AI judge or a rubric, we re-run it on those human-scored examples. If it stops
agreeing with the human, the change is blocked. The judge is held to the same standard as the
product it judges.

## 6. Why we run each test several times (the reliability idea)

Because AI is random, running a test *once* tells you almost nothing — it might have passed by luck.
So Evalyn runs each test a few times and records **two very different numbers**:

- **"Did it pass at least once?"** — the *lenient* score. Good for "can it ever do this?"
- **"Did it pass EVERY single time?"** — the *strict* score. This is the one that matters for
  safety.

**Why the strict score matters so much:** imagine a test that stops the AI leaking a secret, and it
passes 2 times out of 3. The lenient view says "mostly fine!" But the *one* time it fails, a real
user gets the leak. For anything safety-related, "usually safe" is not safe. So **Evalyn requires
safety tests to pass every single time.** (We actually proved this works with a real experiment —
see [the spike findings](./2026-07-22-inspect-spike-findings.md).)

## 7. Three flavors of test

Not every test should be able to fail your build. Evalyn sorts tests into three kinds:

- **Regression tests** — things your product *already gets right*. If one of these breaks, that's a
  real problem → it can fail the build.
- **Safety tests** — a special, stricter regression test that must pass *every* time (§6).
- **"Wish-list" (capability) tests** — things your product *can't do yet* but you hope it will.
  These are *expected* to fail, so they **never** fail your build. They're tracked as goals, and the
  moment your product starts passing one reliably, Evalyn suggests "promote this to a real test now."

This means your test suite grows in two directions: goals get promoted up as the product improves,
and newly-discovered problems drop in from the `discover` mode (next section).

## 8. The flywheel (why Evalyn gets smarter over time)

Here's the loop that makes Evalyn more than a static test list:

1. `discover` mode goes hunting and finds a genuine new problem.
2. **Crucially, it doesn't get to declare victory on its own** — an AI tester is too eager and will
   claim false wins. A finding only counts once the trustworthy grading layer (§5) independently
   *confirms* the problem against the actual conversation. (The tester *proposes*; the grader
   *disposes*.)
3. A confirmed problem is automatically turned into a new, permanent `gate` test.

So every hunting session that finds something real makes your smoke-alarm suite bigger — and the
product **never silently re-breaks that same bug again.** That's the flywheel.

## 9. The guardrails (safety and cost)

This is a tool that generates poking, adversarial traffic and spends money on AI calls, so it has
brakes built in:

- **Address allowlist.** Evalyn refuses to run against any web address you haven't explicitly listed
  in the pack. This prevents "oops, I just red-teamed the live production site" or someone else's app.
- **Spending ceiling.** Each run has a hard dollar limit. Go over it and the run stops gracefully
  with a partial report — never a surprise bill. A `--dry-run` shows you the estimated cost before a
  single real call.
- **Privacy.** Conversations (which might contain sensitive data the AI revealed) are saved locally
  and kept out of git by default.
- **Read-only.** The engine only knows how to *chat* with a product. It has no ability to delete or
  change anything.

## 10. What you actually see when you use it

- **A command line:** you type `evalyn gate --target ./packs/yourproduct` and it runs.
- **A clear pass/fail** (and an exit code, so your CI pipeline understands it).
- **A written report** summarizing what passed, what failed, and what's under review.
- **A saved record of every run** (self-contained, so any two runs can be compared later).
- **A web viewer for free** — because Evalyn is built on top of a proven eval framework (Inspect AI),
  you get its browser viewer to click through every conversation, see each score, and read *why* the
  judge decided what it did.

There's **no fancy custom dashboard in v1** — on purpose. You launch a run, watch it, and review the
results afterward. You can't yet steer the hunting agent live while it runs; that's a future nicety.

## 11. What v1 includes — and deliberately leaves out

**In v1:** testing the AI's *conversational behavior* through its real chat API — the three modes,
the trust ladder, the guardrails, and one worked example product.

**Deliberately not in v1** (to ship something valuable rather than something endless):
- Testing the *whole system* (databases, servers, internal APIs) — behavior only, for now.
- A hosted website/dashboard product — command line and files first.
- Watching live production traffic for quality drift.
- Auto-reconfiguring your product for A/B tests — you bring up each version; Evalyn just tests them.

## 12. Why we're building on Inspect AI (and not from scratch)

There's a proven, open-source framework from the UK's AI Safety Institute called **Inspect AI** that
already solves the boring-but-hard plumbing: running tests reliably, recording results in a standard
format, showing them in a viewer, and talking to different AI providers. Rebuilding that would take
months and never be as good.

So Evalyn **stands on Inspect** for the plumbing and spends all its effort on the parts that are
genuinely ours and new: the reusable *target packs*, the curious *discovery agent*, and the
*flywheel*. We even ran a hands-on experiment (a "spike") to confirm this fit before committing —
and it confirmed Inspect gives us even more than we assumed (it already computes the strict
"pass-every-time" score for us).

---

## 13. Quick glossary (plain English)

| Term | Plain meaning |
|------|---------------|
| **Engine** | The generic machinery. Works with any product. |
| **Target pack** | A folder describing *one* product + its tests. |
| **Probe** | A single test case (one thing you're checking). |
| **Check / grader** | The rule or judge that decides if a probe passed. |
| **Invariant** | A rule that must hold for *every* reply (e.g. "never leak secrets"). |
| **Transcript** | The recorded back-and-forth of a test conversation. |
| **Regression test** | Checks something already works still works. |
| **Capability ("wish-list") test** | Checks something you hope will work; never fails the build. |
| **Safety test** | A test that must pass *every single time*. |
| **pass at least once / pass every time** | The lenient vs strict reliability scores. |
| **Baseline** | A saved "known-good" run to compare new runs against. |
| **The flywheel** | Discovered problems auto-become permanent tests. |
| **Inspect AI** | The proven framework we build the plumbing on. |
| **Spike** | A quick hands-on experiment to de-risk a decision before committing. |

---

*This is a living document — update it whenever the shape of Evalyn changes.*
