---
feature: "{{NAME}}"
phase: "{{PHASE_NUMBER_AND_NAME}}"
status: "{{STATUS}}" # Built | Updated | Deferred
---

# Feature: {{NAME}}

## 1. Overview
* **Name:** {{NAME}}
* **Phase:** {{PHASE_NUMBER_AND_NAME}} — e.g. "Phase 1 — Core, Database, Ledger, LLM Client, Redaction"
* **Purpose:** {{PURPOSE}}
* **Traces to:** {{SPEC_REFERENCE}} — the exact spec or contract requirement this satisfies, e.g. "CONTRACT.md I-8, DATA_MODEL.md section 4".

## 2. Technical Rationale
* **How we achieved it:** {{TECH_SUMMARY}}
* **Alternatives considered:** {{ALTERNATIVES}} — write "none" if the spec dictated this approach directly.
* **Why we chose this path:** {{JUSTIFICATION}}

## 3. Database Schema Impact
* **Changes made:** {{DB_CHANGES}} — e.g., "Added `ledger` table with append-only SQLite triggers". Write "none" if purely application-level code.

## 4. Core Logic & Necessary Functions
* **List of functions & files:** Key functions and classes added or modified, their exact file paths, why they exist, and how they are called.
  * `function_or_class_name` (`exact/path/to/file.py`): {{ROLE_DESCRIPTION}}
    - **Why it is called:** {{WHY_CALLED}}
    - **How it is called & callers:** {{HOW_CALLED}}
  ```python
  # Code snippet representing the signature and interface at the time this feature was built.
  def example_signature(param: str) -> bool:
      ...
  ```

## 5. Testing & Verification
* **Automated tests:** {{TEST_FILE_PATHS}} — reference test IDs from `docs/TEST_PLAN.md` (e.g. T-LEDGER, T-ID).
* **Manually verified:** {{WHAT_WAS_CHECKED_BY_HAND}}

## 6. Dependencies & Deferred Work
* **Depends on:** {{OTHER_FEATURES_OR_EXTERNAL_SERVICES}}
* **Known issues/deferred:** {{ANYTHING_LEFT_INCOMPLETE_OR_A_DELIBERATE_SHORTCUT}} — an honest gap noted here is far more useful than a log that implies everything is finished when it isn't.

---

## Rules for using this template (not part of the log itself — read once, then follow every time)

1. **Never write a real secret value into a log.** Reference credentials by their env var name only (`LLM_API_KEY`, `TAVILY_API_KEY`).
2. **One feature, one file.** If a feature grows across phases, update the original file in its original phase folder.
3. **A genuinely new feature that merely calls or reuses an existing one gets its own new file**, with a cross-reference in Section 6.
4. **Section 4 is mandatory, not optional.** Exact file paths, function roles, why and how they are called are what make this directory useful for navigating and understanding the codebase.
