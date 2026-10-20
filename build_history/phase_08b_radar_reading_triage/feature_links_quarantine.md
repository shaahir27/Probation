---
feature: "Link Substrate & Quarantine Extractor"
phase: "Phase 8b — Link Substrate, Opportunity Radar, Reading Triage"
status: "Built"
---

# Feature: Link Substrate & Quarantine Extractor

## 1. Overview
* **Name:** Link Substrate & Quarantine Extractor
* **Phase:** Phase 8b — Link Substrate, Opportunity Radar, Reading Triage
* **Purpose:** Provides secure URL sanitization, SSRF protection, untrusted HTML quarantine parsing, and structured metadata extraction without leaking raw web text to writers or engine components.
* **Traces to:** `CONTRACT.md` I-22 (quarantine pattern), I-24 (never fetch mail links), `docs/TAVILY_AND_NEW_PACKS.md` section 2, and `docs/TEST_PLAN.md` T-LINK, T-QUAR.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `sanitise_url()` in `links/sanitise.py`: Strips query tracking parameters (`utm_*`, `fbclid`, `gclid`), normalizes scheme/host, validates URL scheme (`http`/`https`), and blocks loopback, private IPv4/IPv6 (RFC 1918), and cloud metadata IP addresses (`169.254.169.254`).
  - Implemented `QuarantineExtractor` in `links/quarantine.py`: Strict process/parser boundary. Truncates untrusted HTML at `quarantine_max_input_chars` (20,000 chars), parses OpenGraph and HTML meta tags safely with `BeautifulSoup` (or HTMLParser), and returns only typed `ExtractedLinkMetadata` (`title`, `description`, `canonical_url`, `language`, `author`). Never exposes raw HTML to caller.
  - Implemented `LinkExtractor` in `links/extract.py`: Coordinates fetching and quarantine extraction with SQLite caching in `link_cache` (14 days TTL) and offline stub support for tests and backtest replays.
* **Alternatives considered:**
  - Allowing writer LLM to read raw web HTML: Explicitly prohibited by `CONTRACT.md` I-22 (quarantine rule).
  - Fetching mail body URLs: Explicitly prohibited by `CONTRACT.md` I-24.
* **Why we chose this path:**
  - Satisfies `CONTRACT.md` invariants I-22 and I-24 strictly.

## 3. Database Schema Impact
* **Changes made:**
  - Uses `link_cache` table in database:
    ```sql
    CREATE TABLE IF NOT EXISTS link_cache (
        url_hash TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT,
        description TEXT,
        canonical_url TEXT,
        extracted_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    ```

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `sanitise_url` (`backend/src/probation/links/sanitise.py`):
    - **Why it is called:** Cleans tracking parameters and blocks SSRF/internal network addresses.
    - **How it is called & callers:** Called before fetching any external URL.
  ```python
  def sanitise_url(raw_url: str) -> str:
      ...
  ```
  * `QuarantineExtractor` (`backend/src/probation/links/quarantine.py`):
    - **Why it is called:** Parses untrusted HTML in isolation to extract structured metadata.
    - **How it is called & callers:** Called by `LinkExtractor` on fetched raw content.
  ```python
  class QuarantineExtractor:
      def extract(self, html_content: str, source_url: str) -> ExtractedLinkMetadata:
          ...
  ```
  * `LinkExtractor` (`backend/src/probation/links/extract.py`):
    - **Why it is called:** High-level cached link extractor.
    - **How it is called & callers:** Called by Radar and Reading packs.
  ```python
  class LinkExtractor:
      def extract_url(self, url: str) -> Optional[ExtractedLinkMetadata]:
          ...
  ```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_links_radar_reading.py` (T-LINK tests: tracking param removal, SSRF block; T-QUAR tests: raw HTML isolation, truncation, structured field validation).
* **Manually verified:**
  - Verified internal IPs like `127.0.0.1`, `10.0.0.1`, `169.254.169.254` raise `ValueError`.

## 6. Dependencies & Deferred Work
* **Depends on:** `beautifulsoup4`, `urllib.parse`.
* **Known issues/deferred:** None.
