---
description: Build one Probation phase: plan, wait for approval, implement, test, report
---

# /run-phase

Use as: `/run-phase N` where N is the phase number from `docs/IMPLEMENTATION_PLAN.md`.

1. Read `AGENTS.md` and `docs/CONTRACT.md`.
2. Read the "Read:" list under Phase N in `docs/IMPLEMENTATION_PLAN.md`, and the matching kickoff prompt in `docs/AGENT_PLAYBOOK.md` section 5.
3. Confirm the previous phases listed under "Depends on" are merged. If not, stop and say so.
4. Create the branch `phase-N-<short-name>`.
5. Produce an implementation plan and task list for THIS phase only. List the files you will create or change and the T- tests you will satisfy. **Stop and wait for approval.**
6. After approval, implement in small commits named `phase-N: <what>`. Write tests first for ledger, no-peeking, licence maths and the gate.
7. Run `make check`. Fix failures by fixing code, never by weakening, skipping or deleting tests.
8. Run any extra acceptance commands listed under Phase N.
9. Document every feature built or modified in `build_history/` following `docs/BUILD_LOGGING_PROTOCOL.md` using `docs/templates/log_schema.md` (exact file paths, key functions, why/how they are called). Write `phase_XX_summary.md` and refresh `build_history/index.md`.
10. Write `docs/reports/phase-N.md` using the template in `docs/AGENT_PLAYBOOK.md` section 6.
11. Stop. Do not start the next phase.

Stop and ask if any item in `docs/AGENT_PLAYBOOK.md` section 9 applies.
