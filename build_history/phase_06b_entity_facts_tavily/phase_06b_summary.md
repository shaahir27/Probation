# Phase 6b Summary: Entity Facts Service (Tavily Vetting)

**Status:** Completed  
**Lane:** Lane B (Member 2: Data & Packs)  
**Deliverables:**
- `backend/src/probation/web/`: `query_guard.py`, `derive.py`, `client.py`, `view.py`, `fixtures.py`, `__init__.py`.
- `backend/src/probation/workers/webfacts.py`: Full worker pipeline under `Role.WEBFACTS`.
- `backend/tests/fixtures/web_facts_fixtures.json`: Recorded offline dataset.
- `backend/tests/unit/test_tavily_webfacts.py`: 16 tests passing `T-WEBQ`, `T-WEBISO`, `T-VET`.
- CLI integration: `probation webfacts vet`, `probation webfacts audit`, `probation webfacts load-fixtures`.
- Replay engine integration: proposal web veto and `proposals.web_json` population.

## Acceptance Criteria Met
- [x] `T-WEBQ` passes: Character whitelisting, 80-char/12-token limits, disallowed substrings, 6-digit runs, `<PERSON_n>`, user name tokens.
- [x] `T-WEBISO` passes: Zero imports from `probation.web` in `policy.py`, `evidence.py`, `licence.py`, and `features.py`. `RestrictionOnly` contains no probability/evidence fields. Autonomy rank never increases with web veto.
- [x] `T-VET` passes: Homoglyph and hyphen lookalike detection, local brand list pre-checks, scam report threshold ($\ge 2$), and status precedence.
- [x] All 120 unit tests, 11 API tests, 3 backtest integration tests, and property tests pass.
- [x] Ruff lint, formatting, and strict Mypy checks clean across entire repository.
