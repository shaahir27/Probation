"""Quarantined extractors and code-side validation for web page content.

Authority: docs/CONTRACT.md invariants I-22, I-26, docs/TAVILY_AND_NEW_PACKS.md section 6,
and docs/PROMPTS.md sections 12-13.
Raw web text is untrusted: only a quarantined extractor reads it, and the writer never sees it.
"""

import re
import sqlite3
from datetime import date, datetime
from typing import Any

from probation.core.clock import get_clock
from probation.core.hashing import canonical_json, det_id
from probation.db.access import Role, RoleAccess
from probation.llm.jobs import LinkExtraction, OpportunityExtraction

EXTRACT_OPPORTUNITY_SCHEMA = OpportunityExtraction.model_json_schema()

EXTRACT_LINK_SCHEMA = LinkExtraction.model_json_schema()

FEE_REGEX_PATTERN = re.compile(
    r"\b(fee|registration fee|payment|pay|upi|inr|rs\.?|entry fee|cost|amount)\b|[₹$€£]",
    re.IGNORECASE,
)


def _strip_control_and_markup(text: str) -> str:
    """Strip markup and non-printable control characters."""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"https?://[^\s<>]+", "", clean, flags=re.IGNORECASE)
    clean = "".join(ch for ch in clean if ch.isprintable() or ch in " \t\n")
    return clean.strip()


def _date_appears_in_text(date_str: str, page_text: str) -> bool:
    """Check if ISO date (YYYY-MM-DD) or common text format appears in page text."""
    if not date_str:
        return False
    if re.search(r"\b\d{1,2}:\d{2}\b", page_text) and not re.search(
        r"\b(?:UTC|GMT|IST|PST|PDT|EST|EDT)\b|[+-]\d{2}:?\d{2}", page_text, re.I
    ):
        return False
    try:
        date.fromisoformat(date_str)
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if re.search(rf"(?<!\d){re.escape(date_str)}(?!\d)", page_text):
            return True
        day = str(dt.day)
        day_padded = f"{dt.day:02d}"
        month_name = dt.strftime("%B")
        month_abbr = dt.strftime("%b")
        year = str(dt.year)

        candidate_patterns = [
            rf"\b{day}(?:st|nd|rd|th)?\s+{month_abbr}\.?\s+{year}\b",
            rf"\b{day}(?:st|nd|rd|th)?\s+{month_name}\s+{year}\b",
            rf"\b{month_abbr}\.?\s+{day}(?:st|nd|rd|th)?,?\s+{year}\b",
            rf"\b{month_name}\s+{day}(?:st|nd|rd|th)?,?\s+{year}\b",
        ]
        # Numeric slash dates are usable only when their order is unambiguous.
        if dt.day > 12:
            candidate_patterns.append(rf"\b{day_padded}/{dt.month:02d}/{year}\b")
            candidate_patterns.append(rf"\b{dt.month:02d}/{day_padded}/{year}\b")
        for pat in candidate_patterns:
            if re.search(pat, page_text, re.IGNORECASE):
                return True
    except ValueError:
        pass
    return False


def _date_has_role(value: str, page: str, role: str) -> bool:
    anchor = (
        r"\b(?:deadline|apply\s+by|applications?\s+clos(?:e|es)|closing\s+date)\b"
        if role == "deadline_date"
        else r"\b(?:(?:program(?:me)?|event|fellowship|course|conference|workshop)\s+"
        r"(?:starts?|begins?|commences?)|start\s+date)\b"
    )
    return any(
        re.search(anchor, sentence, re.I) and _date_appears_in_text(value, sentence)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", page)
    )


def validate_opportunity_fields(
    raw_fields: dict[str, Any],
    page_text: str,
) -> tuple[dict[str, Any], bool, list[str]]:
    """Apply strict code-side validation to opportunity extractor output.

    Authority: docs/PROMPTS.md section 12.
    """
    fields = dict(raw_fields)
    notes: list[str] = []
    validator_ok = True

    # 1. Validate dates literally appear in page text
    for date_key in ("deadline_date", "start_date"):
        d_val = fields.get(date_key)
        if d_val:
            if not _date_appears_in_text(str(d_val), page_text) or not _date_has_role(
                str(d_val), page_text, date_key
            ):
                notes.append(f"{date_key}_unverified: '{d_val}' not in page text")
                fields[date_key] = None
                validator_ok = False

    # 2. fee_mentioned is OR-ed with page text regex
    regex_fee = bool(FEE_REGEX_PATTERN.search(page_text))
    model_fee = bool(fields.get("fee_mentioned", False))
    fields["fee_mentioned"] = model_fee or regex_fee
    if regex_fee and not model_fee:
        notes.append("fee_flag_raised_by_regex")

    # A quoted eligibility claim needs contiguous support, including its negations.
    clean_page_lower = " ".join(page_text.casefold().split())
    validated_eligibility: list[str] = []

    for item in fields.get("eligibility") or []:
        phrase = " ".join(str(item).casefold().split())
        if not phrase:
            continue
        matching_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", clean_page_lower)
            if phrase in sentence
        ]
        if any(
            not re.search(r"\b(?:no|not|except|unless|ineligible|only|must|required)\b", sentence)
            or phrase.rstrip(".!?") == sentence.rstrip(".!?")
            for sentence in matching_sentences
        ):
            validated_eligibility.append(_strip_control_and_markup(str(item)[:100]))
        else:
            notes.append("eligibility_unsupported")
            validator_ok = False
    fields["eligibility"] = validated_eligibility[:3]

    if fields.get("mode") not in {None, "unknown"}:
        signal = {
            "online": r"\bonline\b",
            "in_person": r"\bin[- ]person\b",
            "hybrid": r"\bhybrid\b",
        }.get(str(fields["mode"]))
        if signal is None or not re.search(signal, page_text, re.I):
            fields["mode"] = "unknown"
            validator_ok = False
            notes.append("mode_unverified")

    # 4. Strip control characters from strings
    for k in ("title", "organiser"):
        if fields.get(k):
            fields[k] = _strip_control_and_markup(str(fields[k]))

    # 5. apply_domain must appear in page text
    apply_domain = fields.get("apply_domain")
    if apply_domain:
        clean_domain = str(apply_domain).lower().strip()
        page_urls = re.findall(r"https?://[^\s<>\[\]()]+", page_text, re.IGNORECASE)
        from urllib.parse import urlsplit

        supported_domains = {
            (urlsplit(url.rstrip(".,;")).hostname or "").lower() for url in page_urls
        }
        if clean_domain not in supported_domains:
            notes.append(f"apply_domain_unverified: '{clean_domain}' not in page text")
            fields["apply_domain"] = None
            validator_ok = False

    return fields, validator_ok, notes


def validate_link_fields(
    raw_fields: dict[str, Any],
    page_text: str,
    url_slug: str = "",
) -> tuple[dict[str, Any], bool, list[str]]:
    """Apply code-side validation to link extractor output.

    Authority: docs/PROMPTS.md section 13.
    """
    fields = dict(raw_fields)
    notes: list[str] = []
    validator_ok = True

    # Title verification: must appear in page text or URL slug
    title = fields.get("title")
    if title:
        norm_title = re.sub(r"\s+", " ", str(title).lower().strip())
        norm_page = re.sub(r"\s+", " ", page_text.lower())
        norm_slug = re.sub(r"[-_]+", " ", url_slug.lower())

        if norm_title not in norm_page and norm_title not in norm_slug:
            notes.append(f"title_unverified: '{title[:40]}' not in page or slug")
            fields["title"] = None
            validator_ok = False
        else:
            fields["title"] = _strip_control_and_markup(str(title)[:100])

    return fields, validator_ok, notes


def record_quarantine_output(
    conn: sqlite3.Connection | RoleAccess,
    extraction_id: str,
    prompt_id: str,
    prompt_version: str,
    model_id: str,
    validated_fields: dict[str, Any],
    validator_ok: bool,
    validator_notes: list[str],
    now_iso: str | None = None,
) -> str:
    """Store typed output of quarantined extractor in quarantine_outputs table."""
    now_ts = now_iso or get_clock().now_iso()
    output_id = det_id("quar_out", extraction_id, prompt_id, prompt_version)
    fields_json = canonical_json(validated_fields)
    notes_json = canonical_json(validator_notes)

    access = conn if isinstance(conn, RoleAccess) else RoleAccess(conn, Role.WEBFACTS)
    access.execute_write(
        "quarantine_outputs",
        """
        INSERT OR REPLACE INTO quarantine_outputs
        (id, extraction_id, prompt_id, prompt_version, model_id, fields_json, validator_ok, validator_notes_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            output_id,
            extraction_id,
            prompt_id,
            prompt_version,
            model_id,
            fields_json,
            1 if validator_ok else 0,
            notes_json,
            now_ts,
        ),
    )
    return output_id
