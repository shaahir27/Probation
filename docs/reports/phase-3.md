# Phase 3 Handoff: Mail and Calendar Domain Packs

**Branch:** `phase-3-mail-cal`  
**Phase:** 3 — Mail and Calendar Packs  
**Lane:** Lane A (Member 1)  

---

## Done
1. **Core Domain Types & Pack Protocol**: Extended `backend/src/probation/core/types.py` with `ActionSpec`, `ReaderSpec`, `ExamOperator`, and `ExecResult`. Updated `backend/src/probation/packs/base.py` with `WorldView`, `ExecutorIO`, and the full `PackAdapter` protocol matching `CONTRACT.md` Section 5.
2. **Mail Domain Pack (`packs/mail/`)**:
   - Implemented situation extraction (`email_action`) skipping user-sent, draft, or spam messages, and redacting message body before storage.
   - Built deterministic clue extraction computing all 16 binding clues (`sender_tier`, `sender_domain_class`, `n_prior_in`, `n_prior_replied`, `reply_rate_sender`, `median_reply_hours_sender`, `has_unsubscribe`, `is_noreply`, `hour_of_day`, `weekday`, `is_weekend`, `n_recipients`, `has_attachment`, `in_thread_user_participated`, `thread_length`, `body_len_bucket`) strictly through `HistoryView(as_of=s.occurred_at)`.
   - Built priority-ordered outcome resolution (`REPLY` > `FORWARD` > `TRASH` > `ARCHIVE` > `LEAVE`) with 7-day observation window and right-censoring.
   - Built `SimWorld` execution and undo operations for labels and sent messages.
   - Built 10 exam perturbation operators and validators.
   - Configured prompt template and schema at `backend/src/probation/llm/prompts/reader.mail.v2.md`.
3. **Calendar Domain Pack (`packs/calendar/`)**:
   - Implemented situation extraction (`invite_rsvp`) for inbound invitations with initial `NEEDS-ACTION` status.
   - Built deterministic clue extraction computing all 12 binding clues (`organizer_tier` across mail + calendar, `start_hour_bucket`, `start_weekday`, `duration_min`, `lead_days`, `n_attendees`, `is_recurring`, `conflicts_count`, `adjacent_conflict`, `accept_rate_organizer`, `accept_rate_hour_bucket`, `has_location_or_link`) strictly through `HistoryView`.
   - Built outcome resolution (`ACCEPT`, `DECLINE`, `TENTATIVE`, `NO_RESPONSE`) bounded by `min(event_start, occurred_at + 7 days)` with right-censoring.
   - Built `SimWorld` execution and undo operations for attendee status and `BLOCK_TIME`.
   - Built 6 exam perturbation operators and validators.
   - Configured prompt template and schema at `backend/src/probation/llm/prompts/reader.invite.v1.md`.
4. **Pack Registry**: Built `PackRegistry` in `backend/src/probation/packs/registry.py` with structural conformance validation and automatic registration of `mail_pack` and `calendar_pack`.
5. **Worker Ingestion Pipeline**:
   - Built `ingest_situations` in `backend/src/probation/workers/ingestor.py` parsing raw items under `Role.INGESTOR`.
   - Built `extract_features_for_situations` in `backend/src/probation/workers/brain.py` featurizing situations under `Role.BRAIN`.
   - Wired `probation ingest` subcommand in `backend/src/probation/cli.py`.
6. **Testing & Stubs Harness**:
   - Built `StubReader` in `backend/tests/stubs/stub_reader.py` deriving reader fields from synthetic truth without live LLM calls, preserving static AST isolation.
   - Built `test_pack_conformance.py` covering all 7 `T-PACK` checks.
   - Built `test_outcome_resolvers.py` covering all `T-RESOLVE` priority rankings and window cutoffs.
   - Built `test_ingestor_and_features.py` validating 100% featurization on `tiny_synth`.

---

## Files Changed / Created
- `backend/src/probation/core/types.py` (updated)
- `backend/src/probation/packs/base.py` (updated)
- `backend/src/probation/packs/registry.py` (updated)
- `backend/src/probation/packs/mail/clues.py` (updated)
- `backend/src/probation/packs/mail/resolver.py` (updated)
- `backend/src/probation/packs/mail/executor.py` (updated)
- `backend/src/probation/packs/mail/exam_ops.py` (updated)
- `backend/src/probation/packs/mail/__init__.py` (updated)
- `backend/src/probation/packs/calendar/clues.py` (updated)
- `backend/src/probation/packs/calendar/resolver.py` (updated)
- `backend/src/probation/packs/calendar/executor.py` (updated)
- `backend/src/probation/packs/calendar/exam_ops.py` (updated)
- `backend/src/probation/packs/calendar/__init__.py` (updated)
- `backend/src/probation/llm/prompts/reader.mail.v2.md` (new)
- `backend/src/probation/llm/prompts/reader.invite.v1.md` (new)
- `backend/src/probation/workers/ingestor.py` (updated)
- `backend/src/probation/workers/brain.py` (updated)
- `backend/src/probation/cli.py` (updated)
- `backend/tests/stubs/__init__.py` (new)
- `backend/tests/stubs/stub_reader.py` (new)
- `backend/tests/unit/test_pack_conformance.py` (new)
- `backend/tests/unit/test_outcome_resolvers.py` (new)
- `backend/tests/unit/test_ingestor_and_features.py` (new)
- `build_history/phase_03_mail_calendar_packs/feature_mail_pack.md` (new)
- `build_history/phase_03_mail_calendar_packs/feature_calendar_pack.md` (new)
- `build_history/phase_03_mail_calendar_packs/feature_ingestor_brain_features.md` (new)
- `build_history/phase_03_mail_calendar_packs/phase_03_summary.md` (new)
- `build_history/index.md` (updated)
- `docs/reports/phase-3.md` (new)

---

## Tests
- `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (111 files clean).
  - `mypy --config-file backend/pyproject.toml backend/src/probation`: Passed (0 errors across 91 source files).
  - `pytest -q backend/tests -m "not live"`: 52 passed in 7.37s.
- **Contract Tests Satisfied**:
  - `T-PACK`: All 7 conformance checks pass for both `mail` and `calendar` packs.
  - `T-RESOLVE`: Priority order (reply beats forward beats trash beats archive beats leave), censoring windows, and `known_at` accuracy verified.
  - `T-ID`: Ingestor and brain worker operations are 100% idempotent.
  - `T-SYNTH (Static Isolation)`: `StubReader` lives in `tests/stubs/`, ensuring zero references to `truth.json` in production source code.

---

## Invariants Touched
- **I-6 (No peeking / Temporal Isolation)**: Every deterministic clue queries `HistoryView(as_of=s.occurred_at)` only; verified against mutated future data.
- **I-10 (Role write boundaries)**: Ingestor worker writes strictly to `situations` under `Role.INGESTOR`; brain worker writes strictly to `features` under `Role.BRAIN`.
- **I-14 (Redaction before egress)**: Message bodies and invite titles/descriptions are redacted before storage in `situations.redacted_text`.
- **I-17 (World Isolation)**: Execution and undo run directly against `SimWorld` (`world.db`), decoupled from the engine ledger.

---

## Deviations and Assumptions
- None. All implementations match `CONTRACT.md` and `PACKS_SPEC.md` verbatim.

---

## Contract Change Requests
- None.

---

## New Dependencies
- None.

---

## LLM Cost Incurred
- $0.00 USD (All automated tests utilize `StubReader` test double).

---

## Open Questions
- None.

---

## Suggested Next Step
- Phase 3 is complete and fully verified. Proceed to **Phase 4: Engine core and backtest** (`phase-4-engine-backtest`).
