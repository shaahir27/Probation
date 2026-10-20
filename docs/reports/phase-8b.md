# Phase 8b Handoff: Link Substrate, Opportunity Radar, and Reading Triage

**Branch / commit:** `phase-6-8b-files-links-radar`  
**Phase:** 8b — Link Substrate, Opportunity Radar, Reading Triage  
**Lane:** Lane B (Member 2: Data & Packs)  
**Authority:** [`docs/TAVILY_AND_NEW_PACKS.md`](../TAVILY_AND_NEW_PACKS.md), [`docs/CONTRACT.md`](../CONTRACT.md) invariants I-21 to I-26, [`docs/PACKS_SPEC.md`](../PACKS_SPEC.md) sections 6 & 7, and [`docs/TEST_PLAN.md`](../TEST_PLAN.md) T-LINK, T-QUAR, T-RADAR, T-READING.

---

## Done

1. **URL Sanitiser (`backend/src/probation/links/sanitise.py`)**:
   - Implemented `sanitise_url()`: Removes tracking query params (`utm_*`, `fbclid`, `gclid`, `mc_cid`, `ref`, etc.), strips fragments, and normalizes URL structures.
   - Built comprehensive SSRF / private IP rejection: blocks loopback (`127.0.0.1`, `localhost`), RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local / cloud metadata (`169.254.169.254`), and invalid schemes.
2. **Quarantine Extractor (`backend/src/probation/links/quarantine.py`)**:
   - Implemented strict quarantine boundary for untrusted web content (Invariant `I-22`).
   - Caps input raw HTML at `quarantine_max_input_chars` (20,000 characters).
   - Extracts structured `ExtractedLinkMetadata` only (title, description, canonical_url, site_name, author, language, published_date) using `BeautifulSoup`.
   - Guaranteed that raw untrusted web HTML is never returned or leaked to LLM writers or engine evaluators.
3. **Cached Link Extractor (`backend/src/probation/links/extract.py`)**:
   - Coordinates URL fetching and quarantine extraction with local SQLite caching in `link_cache` (14 days TTL).
   - Includes offline stubs and test mocks ensuring deterministic execution without live network dependencies during tests and backtests.
4. **Opportunity Radar Pack (`backend/src/probation/packs/radar/`)**:
   - `clues.py`: Extracts opportunity clues (title, sponsor entity, deadline, requirements, compensation, fee indicators, sensitive document requests).
   - `out_of_band.py`: Out-of-band sponsor domain validation via `WebFactsView`. Flags scam reports, lookalikes, or unverified zero-presence entities and imposes web veto cap.
   - `executor.py`: Executes `track_opportunity`, `dismiss_opportunity`, and `flag_opportunity` into `SimWorld`'s `tracker` table.
   - `resolver.py`: Evaluates AI triage actions against user ground-truth decisions within `radar_window_days` (14 days) or `radar_min_window_days` (3 days).
   - `digest.py`: Generates formatted opportunity digests with safety badges and direct citations.
   - `exam_ops.py`: Synthesizes canonical, distractor, and adversarial opportunity triage exam cases.
   - Registered under family `opportunity_triage`.
5. **Reading Triage Pack (`backend/src/probation/packs/reading/`)**:
   - `clues.py`: Extracts reading list metadata clues from quarantined link items.
   - `executor.py`: Manages reading list actions (`save_to_library`, `archive_item`, `assign_collection`, `add_tag`) in `SimWorld`'s `library` table.
   - `resolver.py`: Compares reading triage actions against user library history within `reading_window_days` (7 days).
   - `exam_ops.py`: Synthesizes reading list triage exam questions.
   - Registered under family `link_triage`.
6. **SimWorld & API Integration (`backend/src/probation/synth/world.py`, `backend/src/probation/api/routes/boards.py`)**:
   - Extended `SimWorld` schema with `tracker` and `library` tables and CRUD methods.
   - Connected `/api/boards/{pack}` in the FastAPI backend to serve live tracker and library board entries for `radar` and `reading` packs.
7. **Conditional Autonomy Cap (`backend/src/probation/engine/caps.py`)**:
   - Implemented rule in `engine/caps.py`: Any `opportunity_triage` action involving an upfront application fee or personal identity document requests is capped at rank 1 (`PROPOSAL_ONLY`).

---

## Files Changed

- `backend/src/probation/config.py` (updated: added radar, reading, quarantine, and extract tunables)
- `backend/src/probation/synth/world.py` (updated: added tracker and library tables and CRUD methods)
- `backend/src/probation/links/__init__.py` (created/updated: exported sanitise, extract, quarantine)
- `backend/src/probation/links/sanitise.py` (updated: URL sanitisation, tracking strip, SSRF check)
- `backend/src/probation/links/quarantine.py` (created: untrusted HTML quarantine parsing)
- `backend/src/probation/links/extract.py` (updated: cached link extraction)
- `backend/src/probation/packs/radar/__init__.py` (updated: exported pack, clues, resolver, executor, exam_ops, digest)
- `backend/src/probation/packs/radar/clues.py` (created: opportunity clue collector)
- `backend/src/probation/packs/radar/out_of_band.py` (created: out-of-band sponsor domain vetting)
- `backend/src/probation/packs/radar/executor.py` (created: tracker table executor)
- `backend/src/probation/packs/radar/resolver.py` (created: ground-truth resolution)
- `backend/src/probation/packs/radar/digest.py` (created: digest formatting)
- `backend/src/probation/packs/radar/exam_ops.py` (created: exam generators)
- `backend/src/probation/packs/reading/__init__.py` (updated: exported pack, clues, resolver, executor, exam_ops)
- `backend/src/probation/packs/reading/clues.py` (created: reading list clue collector)
- `backend/src/probation/packs/reading/executor.py` (created: library table executor)
- `backend/src/probation/packs/reading/resolver.py` (created: ground-truth resolution)
- `backend/src/probation/packs/reading/exam_ops.py` (created: exam generators)
- `backend/src/probation/packs/base.py` (updated: extended WorldView and ExecutorIO protocols)
- `backend/src/probation/packs/registry.py` (updated: registered radar_pack and reading_pack)
- `backend/src/probation/engine/caps.py` (updated: conditional cap 1 for opportunity triage on fees/docs)
- `backend/src/probation/api/routes/boards.py` (updated: wired radar and reading tracker/library endpoints)
- `backend/tests/unit/test_links_radar_reading.py` (created: 17 unit tests for T-LINK, T-QUAR, T-RADAR, T-READING)
- `backend/tests/unit/test_pack_conformance.py` (updated: conformance tests for all 5 packs)
- `backend/tests/api/test_api_endpoints.py` (updated: tests for radar/reading boards)
- `build_history/phase_08b_radar_reading_triage/feature_links_quarantine.md` (created: build history log)
- `build_history/phase_08b_radar_reading_triage/feature_opportunity_radar.md` (created: build history log)
- `build_history/phase_08b_radar_reading_triage/feature_reading_triage.md` (created: build history log)
- `build_history/phase_08b_radar_reading_triage/phase_08b_summary.md` (created: phase summary)
- `build_history/index.md` (updated: registered Phase 8b logs)
- `docs/reports/phase-8b.md` (created: this report)

---

## Tests

1. **Unit Tests (`pytest -q backend/tests/unit/test_links_radar_reading.py`)**:
   - 17 passed in 0.58s.
   - Tested:
     * `test_sanitise_url_removes_tracking`: Strips `utm_source`, `gclid`, etc.
     * `test_sanitise_url_blocks_private_and_loopback`: Blocks `127.0.0.1`, `10.0.0.1`, `169.254.169.254`.
     * `test_quarantine_extractor_parses_metadata`: Safely extracts OpenGraph and metadata tags.
     * `test_quarantine_extractor_caps_length`: Caps large inputs at 20,000 chars.
     * `test_link_extractor_offline_cache`: Caches extracted metadata and operates offline.
     * `test_radar_clues_extraction`: Validates opportunity clue fields.
     * `test_radar_out_of_band_vetting`: Validates lookalike and scam warning vetoes.
     * `test_radar_conditional_cap_on_fee_or_docs`: Proves cap drops to 1 on fee or sensitive document requests.
     * `test_radar_executor_crud`: Verifies tracking, dismissing, and updating tracker items.
     * `test_radar_resolver`: Verifies user match/mismatch resolution.
     * `test_reading_clues_extraction`: Validates reading list clue extraction.
     * `test_reading_executor_crud`: Verifies library item creation, collection tagging, archiving.
     * `test_reading_resolver`: Verifies reading list habit resolution.
2. **Pack Conformance (`pytest -q backend/tests/unit/test_pack_conformance.py`)**:
   - 6 passed in 0.42s (all 5 packs pass full protocol conformance).
3. **API Endpoints (`pytest -q backend/tests/api/test_api_endpoints.py`)**:
   - 11 passed in 1.48s (including `/api/boards/radar` and `/api/boards/reading`).
4. **Full Test Suite (`pytest -q backend/tests -m "not live"`)**:
   - 177 passed in 48.90s.
5. **Linting & Type Checking**:
   - `ruff check backend`: Clean, 0 errors.
   - `ruff format --check backend`: Clean.
   - `mypy --strict`: Clean, 0 errors across all source files.
6. **Frontend Build**:
   - `npm --prefix frontend run build`: Clean build in 10.97s, 0 errors.

---

## Invariants Touched

- **I-21 (Web facts only restrict/inform, never raise autonomy)**:
  * Out-of-band domain checks only lower or maintain the autonomy cap; verified by static AST isolation and unit tests.
- **I-22 (Untrusted web content quarantine)**:
  * Only `QuarantineExtractor` parses raw web content. Returns structured fields only; raw HTML never leaks to LLM writers or engine policy.
- **I-23 (Web query guard)**:
  * Query guard blocks emails, URLs, names, long runs of digits, and unsafe chars.
- **I-24 (Never fetch URLs from mail bodies)**:
  * Verified: Mail packs do not call link extractors on body text; links originate only from public entity discovery and reading bookmarks.
- **I-25 (Autonomy cap on fee or sensitive document requests)**:
  * `engine/caps.py` enforces `min(cap, 1)` for any `opportunity_triage` task where fee or personal docs are involved.

---

## Deviations and Assumptions

None.

---

## Contract Change Requests

None.

---

## New Dependencies

None. `beautifulsoup4` was already present in requirements.

---

## LLM Cost Incurred

$0.00. (Deterministic logic and recorded offline fixtures).

---

## Open Questions

None.

---

## Suggested Next Step

Phase 10 — Evaluation (Benchmark suites, baseline B3, ablation runs, and final results reporting).
