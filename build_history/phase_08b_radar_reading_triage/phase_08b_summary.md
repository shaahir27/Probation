# Phase 08b Summary: Link Substrate, Opportunity Radar, and Reading Triage

## Executive Overview
Phase 8b delivers the web link substrate and the two link-focused packs: Opportunity Radar (`packs/radar`) and Reading Triage (`packs/reading`), along with the quarantine boundary (`links/quarantine.py`) and URL sanitizer (`links/sanitise.py`).

## Key Deliverables
1. **Link Substrate**:
   - `backend/src/probation/links/sanitise.py`: Tracking parameter removal and SSRF protection.
   - `backend/src/probation/links/quarantine.py`: Raw HTML quarantine isolation and structured OpenGraph/meta extraction.
   - `backend/src/probation/links/extract.py`: Cached link metadata extraction.
2. **Opportunity Radar Pack**:
   - `backend/src/probation/packs/radar/clues.py`: Opportunity clue collector.
   - `backend/src/probation/packs/radar/out_of_band.py`: Out-of-band sponsor domain vetting via WebFacts.
   - `backend/src/probation/packs/radar/executor.py`: Opportunity tracker executor.
   - `backend/src/probation/packs/radar/resolver.py`: Ground-truth resolution.
   - `backend/src/probation/packs/radar/digest.py`: Prioritized opportunity digest generator.
   - `backend/src/probation/packs/radar/exam_ops.py`: Synthetic exam operators.
   - `backend/src/probation/packs/radar/__init__.py`: Registered under family `opportunity_triage`.
3. **Reading Triage Pack**:
   - `backend/src/probation/packs/reading/clues.py`: Reading clue collector.
   - `backend/src/probation/packs/reading/executor.py`: Library entry manager.
   - `backend/src/probation/packs/reading/resolver.py`: User reading habit resolution.
   - `backend/src/probation/packs/reading/exam_ops.py`: Synthetic exam operators.
   - `backend/src/probation/packs/reading/__init__.py`: Registered under family `link_triage`.
4. **World & API Integration**:
   - Extended `SimWorld` with `tracker` and `library` tables and methods.
   - Wired live data into `backend/src/probation/api/routes/boards.py` for `/api/boards/radar` and `/api/boards/reading`.
   - Added conditional cap 1 in `backend/src/probation/engine/caps.py` for fees/personal documents.
5. **Verification**:
   - 17 unit tests in `backend/tests/unit/test_links_radar_reading.py`.
   - Conformance verified in `backend/tests/unit/test_pack_conformance.py`.
