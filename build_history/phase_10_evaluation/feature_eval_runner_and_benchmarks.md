---
feature: "Evaluation Runner Orchestrator, CLI & Benchmark Artifacts"
phase: "Phase 10 — Evaluation & Benchmarks"
status: "Built"
---

# Feature: Evaluation Runner Orchestrator, CLI & Benchmark Artifacts

## 1. Overview
* **Name:** Evaluation Runner Orchestrator, CLI & Benchmark Artifacts
* **Phase:** Phase 10 — Evaluation & Benchmarks
* **Purpose:** Provides end-to-end orchestration to benchmark Probation against baselines B0–B3, component ablations E3, drift safety E4, exam board E5, chains E6, and resource efficiency E7, exporting results to `docs/results/main.json` and `docs/results/tables.md`.
* **Traces to:** `docs/EVALUATION_PLAN.md` sections 5, 6, 7, 8, `docs/TEST_PLAN.md` T-EVAL, `Makefile`.

## 2. Technical Rationale
* **How we achieved it:** Implemented `backend/src/probation/eval/run_eval.py` to ingest historical database situations and counterfactual `truth.json` files, compute empirical metrics, and output structured JSON and GitHub-flavored markdown tables. Implemented `backend/src/probation/eval/human_study.py` to simulate 150-item synthetic human study learning curves. Wired CLI subcommands `probation eval run` and `probation eval report` into Typer in `backend/src/probation/cli.py` with backward compatibility for `make eval SUITE=main`.
* **Alternatives considered:** Relying on ad-hoc Jupyter notebooks or manual reporting scripts was rejected because Probation's verification demands automated, reproducible CLI commands (`make eval`) integrated into CI.
* **Why we chose this path:** Single unified CLI command with full report formatting and automated JSON artifact generation.

## 3. Database Schema Impact
* **Changes made:** None. The evaluation orchestrator reads from `situations`, `proposals`, `outcomes`, `drift_state`, `exams`, `chains`, `habits`, `exposure_log`, and `tavily_calls`.

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `run_evaluation` (`backend/src/probation/eval/run_eval.py`): Primary benchmark runner executing Probation and Baselines B0–B3 over historical situations and counterfactual truth.
  * `format_results_markdown` (`backend/src/probation/eval/run_eval.py`): Renders results into clear markdown tables for `docs/results/tables.md`.
  * `export_evaluation_results` (`backend/src/probation/eval/run_eval.py`): Exports results JSON and markdown summary to `docs/results/`.
  * `generate_human_study_items` (`backend/src/probation/eval/human_study.py`): Generates 150-item balanced study pool (60 mails, 40 invites, 50 files).
  * `run_human_study_simulation` (`backend/src/probation/eval/human_study.py`): Simulates noisy human decision patterns and computes walk-forward learning curves.
  * `eval_run_cmd` & `eval_report_cmd` (`backend/src/probation/cli.py`): Typer CLI commands for running benchmark suites and rendering reports.

```python
def run_evaluation(
    db_path: Path | None = None,
    truth_path: Path | None = None,
    suite: str = "main",
    seed: int = 1,
) -> dict[str, Any]:
    ...
```

## 5. Testing & Verification
* **Automated tests:**
  * `backend/tests/unit/test_eval.py`:
    * `test_human_study_simulation`: Verified 150 items generation, simulated participants, and positive learning progression.
    * `test_run_eval_orchestrator`: Verified runner orchestration, schema conformity, and artifact export.
  * `backend/tests/unit/test_cli_commands.py`: Verified `probation eval` CLI execution.
* **Manually verified:**
  * Ran `python -m probation.cli eval run --suite main` exporting `docs/results/main.json` and `docs/results/tables.md`.
  * Ran `python -m probation.cli eval report` rendering report table to console.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.eval.metrics`, `probation.eval.baselines`, `probation.eval.human_study`.
* **Known issues/deferred:** Full 20-persona evaluation benchmark can be executed with live Nebius/Tavily keys whenever multi-persona dataset generation is triggered (`make synth PERSONA=N`).
