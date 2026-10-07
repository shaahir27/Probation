---
description: Independently review one finished Probation phase against the contract and tests
---

# /verify-phase

Use as: `/verify-phase N`. Run this in a **fresh chat** (not the agent that built the phase). You are a reviewer. Do not change code. Write findings only.

1. Read `AGENTS.md`, `docs/CONTRACT.md`, the Phase N section of `docs/IMPLEMENTATION_PLAN.md`, and `docs/TEST_PLAN.md` section 5 (phase gates).
2. Check out the phase branch on a clean working tree and run `make check`. Record the result.
3. For each T- test required for this phase, find it and confirm it exists and is meaningful (not trivially true, not mocking the thing under test).
4. Static checks. Search the code and report any hit:
   - `datetime.now(` or `time.time(` outside `core/clock.py`
   - network libraries (`httpx`, `requests`, `openai`, `urllib`, `socket`) outside `llm/client.py`, pack connectors and `workers/executor.py`
   - any import of executor credentials or pack `execute` modules from `workers/brain.py` or `workers/examiner.py`
   - SQL `UPDATE` or `DELETE` on the `ledger` table
   - reads of `truth.json` or `data/private/` from engine code
5. Compare behaviour to the docs: pick three specific rules from `ENGINE_SPEC.md`, `PACKS_SPEC.md` or `CONTRACT.md` that this phase touches and confirm the code matches them exactly (numbers, order of checks, names).
6. Confirm `docs/CONTRACT.md` is unchanged (`git diff main -- docs/CONTRACT.md`).
7. Check for secrets, real data, large generated files, and unlisted new dependencies.
8. Verify that feature logs exist in `build_history/` for this phase, matching `docs/BUILD_LOGGING_PROTOCOL.md` (exact file paths and functions documented), that `phase_XX_summary.md` exists, and that `build_history/index.md` is updated.
9. Write `docs/reports/phase-N-review.md` with: PASS or FAIL, a list of findings (blocking and non-blocking), and exact reproduction steps for each blocking finding.
