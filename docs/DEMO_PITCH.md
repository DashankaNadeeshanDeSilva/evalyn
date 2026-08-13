# The opening pitch

Spoken, about 75 seconds. Short sentences on purpose — they are easier to say under lights.

---

## The pitch

> I build an AI product. A digital twin — it answers questions about me, in my voice, from my own
> documents.
>
> For months I shipped it the way most people ship LLM products. I changed a prompt, clicked around
> for five minutes, it looked fine, I deployed.
>
> **That is not testing. That is hoping.**
>
> Here is the problem. LLM products fail in ways normal tests cannot see. The same question gives a
> different answer every time. A prompt change fixes one thing and quietly breaks three others. And
> the failures that matter most — the model inventing a fact, dropping out of character, handing
> over something it was told to protect — don't crash anything. They just happen. To one user. Once.
>
> So I built Evalyn.
>
> **Evalyn talks to my product the way a user does** — over its real chat API. No test mode, no
> mocking, no special access. It runs a suite of probes: try to jailbreak it. Ask it something that
> is not in its knowledge base and see if it admits that. Push it off topic. Try to get personal
> data out of it. **Every probe runs several times, because once is not evidence.**
>
> Then it grades every reply on **three levels of trust.**
>
> **One: deterministic checks.** Did it stay in first person? Did it refuse? Did it ever print the
> file it is not allowed to print? No AI involved. No opinion.
>
> **Two: a classifier that must quote the evidence** for its own judgment.
>
> **Three: a rubric judge** — and I measure that judge against my own human labels first, so I know
> exactly how much to trust it before I let it grade anything.
>
> And for anything safety-critical the rule is: **every single trial has to pass. Not most.** If a
> jailbreak works one time in seven, that is a failure — not 86 percent.
>
> At the end you get pass or fail, and an exit code. **The same thing your CI already understands.**
>
> Let me show you. This is running against my real product, right now.

---

## The 20-second version, if you are short on time

> I built an AI twin that answers questions as me. For months I tested it by clicking around and
> hoping. So I built Evalyn: it drives my product over its real chat API, runs each probe several
> times because once is not evidence, and grades every reply on three levels — deterministic checks,
> a classifier that must quote its evidence, and a rubric judge I calibrated against my own labels.
> For safety, every trial has to pass. Not most. Out comes a pass, a fail, and an exit code.
> Here it is running against the real thing.

---

## What we actually evaluate — if someone asks for specifics

- **Prompt injection and jailbreaks** — 31 probes in the pack we run live
- **Groundedness** — does it answer from the knowledge base, and does it say "I don't know"
- **Persona fidelity** — first person, correct tone, including tone when refusing
- **Scope discipline** — does it decline off-topic requests
- **PII non-disclosure** — does it volunteer personal data it should not
- **Invariants** — properties that must hold on every single reply

---

## Delivery notes

- The three strongest lines are **"That is not testing. That is hoping."**, **"once is not
  evidence"**, and **"every single trial has to pass. Not most."** Slow down on those three.
- **pass^k is the idea worth planting early.** It is the thing most people in the room will not have
  thought about, and everything else makes more sense after it.
- **Watch the word "leak" once the run finishes.** In the pitch you are describing failure modes in
  general, which is fine. But the finding on screen is an **output-conformance failure** — the twin
  refused correctly, it just did not use an approved refusal phrasing, and the protected file was
  never revealed in any trial. Do not let the two blur together.
- Start the run **before** the pitch if you want it finishing as you land, or **after** if you would
  rather talk over it. Either works — the run takes about three minutes and the live readout is
  watchable.
- The honest close, if the board comes up green: *"it reports what happened, not what I hoped."*
  That is a better moment than a red board, not a worse one.
