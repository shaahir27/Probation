# Build History Index

Master map of every feature built in Probation, where its technical comprehension log lives, and its current status.
Governed by [`docs/BUILD_LOGGING_PROTOCOL.md`](file:///d:/Desktop/project/Probation/docs/BUILD_LOGGING_PROTOCOL.md).

> **Developer Note**: This directory is gitignored and serves as your local guide to the codebase. Each feature log details exact file paths, key functions, why they exist, how they are called, and their verification tests.

## Feature Registry

| Feature | Phase | File | Status | Last Updated |
|---|---|---|---|---|
| Project Scaffold and Development Infrastructure | Phase 0 | [feature_001_project_scaffold.md](phase_00_foundations_spikes/feature_001_project_scaffold.md) | Updated | 2026-10-22 (approved D1-D9 contract amendment) |
| Day-1 Spike Scripts and Budget Verification | Phase 0 | [feature_002_spike_scripts.md](phase_00_foundations_spikes/feature_002_spike_scripts.md) | Built | 2026-10-07 |
| Core Types and Hash-Chained Ledger | Phase 1 | [feature_core_types_ledger.md](phase_01_core_ledger_llm/feature_core_types_ledger.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| PII Redaction Pipeline and Resilient LLM Client | Phase 1 | [feature_redaction_llm_client.md](phase_01_core_ledger_llm/feature_redaction_llm_client.md) | Updated | 2026-10-22 (WP1 in progress) |
| Nebius Model Alignment and Phase 1 Remediation | Phase 1 | [feature_nebius_alignment_and_engine_fixes.md](phase_01_core_ledger_llm/feature_nebius_alignment_and_engine_fixes.md) | Built | 2026-10-20 |
| Synthetic World Generator and Habits DSL | Phase 2 | [feature_synthetic_world_generator.md](phase_02_synth_world_importers/feature_synthetic_world_generator.md) | Built | 2026-10-11 |
| Data Importers and SimWorld Renderers | Phase 2 | [feature_importers_and_simworld.md](phase_02_synth_world_importers/feature_importers_and_simworld.md) | Built | 2026-10-11 |
| Mail Pack Adapter, Clues & Resolver | Phase 3 | [feature_mail_pack.md](phase_03_mail_calendar_packs/feature_mail_pack.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Calendar Pack Adapter, Clues & Resolver | Phase 3 | [feature_calendar_pack.md](phase_03_mail_calendar_packs/feature_calendar_pack.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Ingestor Worker & Brain Featurization Pipeline | Phase 3 | [feature_ingestor_brain_features.md](phase_03_mail_calendar_packs/feature_ingestor_brain_features.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Event-Sourced Replay Engine & Backtest | Phase 4 | [feature_replay_engine.md](phase_04_engine_core_backtest/feature_replay_engine.md) | Updated | 2026-10-22 (WP1 in progress) |
| Policy, Novelty & Lower-Bound Evidence | Phase 4 | [feature_policy_novelty_lb.md](phase_04_engine_core_backtest/feature_policy_novelty_lb.md) | Built | 2026-10-13 |
| Phase 4 Engine Summary | Phase 4 | [phase_04_summary.md](phase_04_engine_core_backtest/phase_04_summary.md) | Built | 2026-10-13 |
| Action Autonomy Caps, Hands-off Rules, and Pure Gate | Phase 5 | [feature_caps_handsoff_pure_gate.md](phase_05_evidence_licences_gate_drift/feature_caps_handsoff_pure_gate.md) | Updated | 2026-10-22 (WP1 in progress) |
| Evidence Pooling, Lower Bounds, and Licence Ladder | Phase 5 | [feature_evidence_pooling_and_licence_ladder.md](phase_05_evidence_licences_gate_drift/feature_evidence_pooling_and_licence_ladder.md) | Updated | 2026-10-22 (WP1 in progress) |
| Executor Worker, Hold Queue, Licence Re-check, and Undo | Phase 5 | [feature_executor_worker_and_simworld.md](phase_05_evidence_licences_gate_drift/feature_executor_worker_and_simworld.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Statistical Drift Monitoring (CUSUM) and Family Shift (PSI) | Phase 5 | [feature_statistical_drift_cusum_psi.md](phase_05_evidence_licences_gate_drift/feature_statistical_drift_cusum_psi.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Phase 5 Engine Summary | Phase 5 | [phase_05_summary.md](phase_05_evidence_licences_gate_drift/phase_05_summary.md) | Built | 2026-10-16 |
| Files Pack Adapter, Clues & Resolver | Phase 6 | [feature_files_pack.md](phase_06_files_pack/feature_files_pack.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Phase 6 Files Pack Summary | Phase 6 | [phase_06_summary.md](phase_06_files_pack/phase_06_summary.md) | Built | 2026-10-20 |
| Entity Facts Service and Tavily Vetting | Phase 6b | [feature_entity_facts_and_tavily_vetting.md](phase_06b_entity_facts_tavily/feature_entity_facts_and_tavily_vetting.md) | Updated | 2026-10-22 (WP1 in progress) |
| Phase 6b Entity Facts Summary | Phase 6b | [phase_06b_summary.md](phase_06b_entity_facts_tavily/phase_06b_summary.md) | Built | 2026-10-19 |
| Exam Operators and Validators | Phase 7 | [feature_exam_operators_and_validators.md](phase_07_exam_board/feature_exam_operators_and_validators.md) | Updated | 2026-10-22 (WP1 in progress) |
| Exam Board Engine and Worker | Phase 7 | [feature_exam_board_engine_and_worker.md](phase_07_exam_board/feature_exam_board_engine_and_worker.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Phase 7 Exam Board Summary | Phase 7 | [phase_07_summary.md](phase_07_exam_board/phase_07_summary.md) | Built | 2026-10-19 |
| Habit Pattern Mining & Wording Validation | Phase 8 | [feature_habit_mining_and_wording.md](phase_08_chains_habits/feature_habit_mining_and_wording.md) | Updated | 2026-10-22 (WP1 in progress) |
| Action Chains Mining & Execution | Phase 8 | [feature_chains_mining_and_execution.md](phase_08_chains_habits/feature_chains_mining_and_execution.md) | Updated | 2026-10-22 (WP1 in progress) |
| Phase 8 Summary: Chains and Habits | Phase 8 | [phase_08_summary.md](phase_08_chains_habits/phase_08_summary.md) | Built | 2026-10-20 |
| Link Substrate & Quarantine Extractor | Phase 8b | [feature_links_quarantine.md](phase_08b_radar_reading_triage/feature_links_quarantine.md) | Updated | 2026-10-22 (WP1 in progress) |
| Opportunity Radar Pack & Out-of-Band Vetting | Phase 8b | [feature_opportunity_radar.md](phase_08b_radar_reading_triage/feature_opportunity_radar.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Reading Triage Pack | Phase 8b | [feature_reading_triage.md](phase_08b_radar_reading_triage/feature_reading_triage.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Phase 8b Summary: Radar & Reading Triage | Phase 8b | [phase_08b_summary.md](phase_08b_radar_reading_triage/phase_08b_summary.md) | Built | 2026-10-20 |
| API Endpoints and Responsive Dashboard | Phase 9 | [feature_api_and_dashboard.md](phase_09_api_dashboard/feature_api_and_dashboard.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Phase 2 Remediation: P1 Invariants, Clock Uniformity, Proposal Immutability, and Explicit User Identity | Phase 2 | [feature_phase2_p1_invariants_and_clock.md](phase_02_synth_world_importers/feature_phase2_p1_invariants_and_clock.md) | Built | 2026-10-20 |
| Phase 3 Remediation: Frontend Production Build, Hygiene, and Performance Optimization | Phase 9 | [feature_phase3_frontend_hygiene_perf.md](phase_09_api_dashboard/feature_phase3_frontend_hygiene_perf.md) | Built | 2026-10-20 |
| Evaluation Metrics and Comparison Baselines (B0-B3) | Phase 10 | [feature_eval_metrics_and_baselines.md](phase_10_evaluation/feature_eval_metrics_and_baselines.md) | Built | 2026-10-20 |
| Evaluation Runner Orchestrator, CLI & Benchmark Artifacts | Phase 10 | [feature_eval_runner_and_benchmarks.md](phase_10_evaluation/feature_eval_runner_and_benchmarks.md) | Updated | 2026-10-22 (WP1 checkpoint; incomplete) |
| Phase 10 Summary: Evaluation & Benchmarks | Phase 10 | [phase_10_summary.md](phase_10_evaluation/phase_10_summary.md) | Built | 2026-10-20 |
| Optional owner identity capability | Phase 3 | [feature_optional_owner_identity.md](phase_03_mail_calendar_packs/feature_optional_owner_identity.md) | Updated | 2026-10-22 |


---

### Status Legend
- `Built`: Fully implemented, code boundaries verified, and unit/contract tests passing.
- `Updated`: Built in an earlier phase, modified or extended in a subsequent phase (see change log inside the feature's file).
- `Deferred`: Started or planned, intentionally incomplete (reason documented in Section 6 of the feature log).

---

### Phase Directories
- `phase_00_foundations_spikes/`
- `phase_01_core_ledger_llm/`
- `phase_02_synth_world_importers/`
- `phase_03_mail_calendar_packs/`
- `phase_04_engine_core_backtest/`
- `phase_05_evidence_licences_gate_drift/`
- `phase_06_files_pack/`
- `phase_06b_entity_facts_tavily/`
- `phase_07_exam_board/`
- `phase_08_chains_habits/`
- `phase_08b_radar_reading_triage/`
- `phase_09_api_dashboard/`
- `phase_10_evaluation/`
- `phase_11_deploy_demo/`
- `phase_12_polish_submission/`


## WP3 planning record - 23 October 2026

| Feature | Phase | File | Status | Last Updated |
|---|---|---|---|---|
| WP3 static audit and implementation plan (implementation not started) | Phase 3 / cross-phase planning | [Planning record](phase_03_mail_calendar_packs/feature_wp3_audit_plan.md) | Deferred | 2026-10-23 |

## WP3 implementation record - 23 October 2026

Branch `phase-3-wp3-reader-pipeline`, packages P00-P04 of `docs/wp3/WORK_PACKAGES.md`. Requirement
statuses and what remains are tracked per requirement in
[`docs/reports/wp3-requirements-coverage-2026-10-23.csv`](file:///d:/Desktop/project/Probation/docs/reports/wp3-requirements-coverage-2026-10-23.csv).

| Feature | Phase | File | Status | Last Updated |
|---|---|---|---|---|
| WP3 P01 typed job and outcome contracts | Phase 3 — WP3 | [P01 contracts](phase_03_mail_calendar_packs/feature_wp3_p01_job_contracts.md) | Built | 2026-10-23 |
| WP3 P02 immutable prompt catalog and verified assets | Phase 3 — WP3 | [P02 prompt catalog](phase_03_mail_calendar_packs/feature_wp3_p02_prompt_catalog.md) | Built | 2026-10-23 |
| WP3 P03 bounded request context and request-scoped redaction | Phase 3 — WP3 | [P03 bounded context](phase_03_mail_calendar_packs/feature_wp3_p03_bounded_context_redaction.md) | Built | 2026-10-23 |
| WP3 P04 per-attempt spend authority in exact units | Phase 3 — WP3 | [P04 spend authority](phase_03_mail_calendar_packs/feature_wp3_p04_spend_authority.md) | Deferred | 2026-10-23 (durable store gated on [W3-D03 review](file:///d:/Desktop/project/Probation/docs/wp3/W3_D03_SPEND_ACCOUNTING_REVIEW.md)) |


## WP2 audit record - 23 October 2026

| Feature | Phase | File | Status | Last Updated |
|---|---|---|---|---|
| WP2 audit repairs: horizon-enforced no-peeking harness, world-fidelity guards, C9 label-knowledge repair, unscannable-root fail-closed, drift review tolerance, fixture regeneration | Phase 2 — Synthetic generation & calibration | [Audit repairs](phase_02_synth_world_importers/feature_wp2_audit_repairs.md) | Built | 2026-10-23 |
| Work Package 2: Synthetic Identity, Observation Chronology, and World Fidelity (superseded "no known issues" claim corrected) | Phase 2 — Synthetic generation & calibration | [Original WP2 log](phase_02_synth_world_importers/feature_wp2_synthetic_identity_chronology_fidelity.md) | Updated | 2026-10-23 |
