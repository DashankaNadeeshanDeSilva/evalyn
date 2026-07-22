# Plan #1 kick-off prompt (for a fresh Claude Code session)

**How to use this:** open a new Claude Code session *in the Evalyn repo*
(`/Users/dashankadesilva/Drive/Projects/Evalyn_eval_agent`) and paste the block below as your first
message. It gives a zero-context session everything it needs to start building Plan #1 the way we
agreed. (A good moment to `/clear` and start fresh — all context is already committed to docs.)

---

## ⬇️ Copy everything below this line into the new session

I want to execute **Plan #1** of the Evalyn project — the gate-first foundation. Please use the
**superpowers:subagent-driven-development** skill to drive it.

**Read these first, in order, to get full context (I have no memory of prior sessions):**
1. `docs/CONTEXT.md` — what Evalyn is, the locked decisions, and my working preferences.
2. `docs/EVALYN_EXPLAINED.md` — the plain-English overview of the product.
3. `docs/superpowers/plans/ROADMAP.md` — how the 3 plans are staged and where Plan #1 fits.
4. `docs/2026-07-22-inspect-spike-findings.md` — the validated Inspect AI fit + the key
   architecture finding (per-probe pass/fail policy lives in Evalyn's gate-diff layer).
5. **`docs/superpowers/plans/2026-07-22-evalyn-gate-foundation.md`** — THE PLAN to execute. It has
   14 test-first tasks with complete code and its own Global Constraints section.

**How I want it executed:**
- **Subagent-driven:** a fresh implementer subagent per task (test-first / TDD, as the plan
  specifies), then a task reviewer, then fixes if needed — exactly as the skill describes.
- **Pause after each task.** This overrides the skill's default "run all tasks without stopping."
  After each task's review comes back clean, **stop and show me a short summary** (what was built,
  tests passing, the commit) and wait for my go-ahead before starting the next task. I want to stay
  in control without watching every keystroke.
- **Model choice:** the plan's tasks contain complete code, so most are transcription-plus-testing —
  use a cheap/fast model for those implementers, a standard model for reviewers, and the most
  capable model for the final whole-branch review. Always set the model explicitly per subagent.

**Before Task 1 — settle two things with me:**
1. **Branch.** We must NOT build on `master` without my consent (docs have been going to `master`,
   but this is real source code). Recommend a branch — I'm inclined toward a feature branch like
   `feat/gate-foundation` (or a git worktree via superpowers:using-git-worktrees). Ask me, then
   create it.
2. **Environment.** A project-root `.venv` and a `spike/` folder already exist from the earlier
   Inspect spike (both git-ignored). Task 1 creates the real `pyproject.toml`; running `uv sync`
   will formalize the project environment. Confirm `uv` is being used (it is: `~/.local/bin/uv`,
   Python 3.12).

**Hard constraints (also in the plan's Global Constraints — do not deviate):**
- **All git commits under my name only — NO `Co-Authored-By` / Claude trailer.** Use
  `git -c user.name='dashankanadeeshandesilva' -c user.email='dashankadesilva@gmail.com' commit ...`.
- **Never push or open/update a PR without asking me first.**
- **Verification before completion:** every task must actually run its tests and show real passing
  output before it's called done — evidence, not assertions.
- Pin `inspect_ai>=0.3.249`; external HTTP is async `httpx` only; the package/CLI name is `evalyn`.

**Definition of done for Plan #1:** `evalyn gate --target packs/example` and
`evalyn validate-pack packs/example` both run end-to-end against the practice target
(`examples/toy_target.py`), the full test suite is green, and `ruff` is clean — as specified in the
plan's Task 14.

Please start by reading the docs above, do the pre-flight plan scan the skill calls for, ask me the
branch/environment questions, and then begin Task 1.

## ⬆️ Copy everything above this line
