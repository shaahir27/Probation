"""Quarantined extractors and code-side validation for web page content.

Authority: docs/CONTRACT.md invariants I-22, I-26, docs/TAVILY_AND_NEW_PACKS.md section 6,
and docs/PROMPTS.md sections 12-13.
Raw web text is untrusted: only a quarantined extractor reads it, and the writer never sees it.
"""

import re
import sqlite3
from datetime import datetime
from typing import Any

from probation.core.hashing import canonical_json, det_id

EXTRACT_OPPORTUNITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "organiser",
        "deadline_date",
        "start_date",
        "eligibility",
        "fee_mentioned",
        "mode",
        "apply_domain",
    ],
    "properties": {
        "title": {"type": ["string", "null"], "maxLength": 80},
        "organiser": {"type": ["string", "null"], "maxLength": 60},
        "deadline_date": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "start_date": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "eligibility": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 100},
        },
        "fee_mentioned": {"type": "boolean"},
        "mode": {"enum": ["online", "in_person", "hybrid", "unknown"]},
        "apply_domain": {"type": ["string", "null"], "maxLength": 80},
    },
}

EXTRACT_LINK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "topic", "content_type", "actionable"],
    "properties": {
        "title": {"type": ["string", "null"], "maxLength": 100},
        "topic": {
            "enum": [
                "programming",
                "ai_ml",
                "web_dev",
                "data",
                "security",
                "career",
                "college",
                "finance",
                "health",
                "design",
                "science",
                "news",
                "other",
            ]
        },
        "content_type": {
            "enum": [
                "article",
                "paper",
                "video",
                "docs",
                "tutorial",
                "repo",
                "product",
                "forum",
                "social",
                "other",
            ]
        },
        "actionable": {"type": "boolean"},
    },
}

FEE_REGEX_PATTERN = re.compile(
    r"\b(fee|registration fee|payment|pay|upi|inr|rs\.?|entry fee|cost|amount)\b|[₹$€£]",
    re.IGNORECASE,
)


def _strip_control_and_markup(text: str) -> str:
    """Strip markup and non-printable control characters."""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = "".join(ch for ch in clean if ch.isprintable() or ch in " \t\n")
    return clean.strip()


def _date_appears_in_text(date_str: str, page_text: str) -> bool:
    """Check if ISO date (YYYY-MM-DD) or common text format appears in page text."""
    if not date_str:
        return False
    if date_str in page_text:
        return True
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day = str(dt.day)
        day_padded = f"{dt.day:02d}"
        month_name = dt.strftime("%B")
        month_abbr = dt.strftime("%b")
        year = str(dt.year)

        candidate_patterns = [
            rf"{day}\s+{month_abbr}\s+{year}",
            rf"{day}\s+{month_name}\s+{year}",
            rf"{month_abbr}\s+{day},?\s+{year}",
            rf"{month_name}\s+{day},?\s+{year}",
            rf"{day_padded}/{dt.month:02d}/{year}",
            rf"{dt.month:02d}/{day_padded}/{year}",
        ]
        for pat in candidate_patterns:
            if re.search(pat, page_text, re.IGNORECASE):
                return True
    except Exception:
        pass
    return False


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
            if not _date_appears_in_text(str(d_val), page_text):
                notes.append(f"{date_key}_unverified: '{d_val}' not in page text")
                fields[date_key] = None
                validator_ok = False

    # 2. fee_mentioned is OR-ed with page text regex
    regex_fee = bool(FEE_REGEX_PATTERN.search(page_text))
    model_fee = bool(fields.get("fee_mentioned", False))
    fields["fee_mentioned"] = model_fee or regex_fee
    if regex_fee and not model_fee:
        notes.append("fee_flag_raised_by_regex")

    # 3. Eligibility word overlap check >= 60%
    clean_page_lower = page_text.lower()
    page_words = set(re.findall(r"\w+", clean_page_lower))
    validated_eligibility: list[str] = []

    for item in fields.get("eligibility") or []:
        item_words = re.findall(r"\w+", str(item).lower())
        if not item_words:
            continue
        overlap = sum(1 for w in item_words if w in page_words)
        ratio = overlap / float(len(item_words))
        if ratio >= 0.60:
            validated_eligibility.append(_strip_control_and_markup(str(item)[:100]))
        else:
            notes.append(f"eligibility_dropped_low_overlap: '{item[:30]}...' ({ratio:.2f})")
            validator_ok = False
    fields["eligibility"] = validated_eligibility[:3]

    # 4. Strip control characters from strings
    for k in ("title", "organiser"):
        if fields.get(k):
            fields[k] = _strip_control_and_markup(str(fields[k]))

    # 5. apply_domain must appear in page text
    apply_domain = fields.get("apply_domain")
    if apply_domain:
        clean_domain = str(apply_domain).lower().strip()
        if clean_domain not in clean_page_lower:
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
    conn: sqlite3.Connection,
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
    now_ts = now_iso or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    output_id = det_id("quar_out", extraction_id, prompt_id, prompt_version)
    fields_json = canonical_json(validated_fields)
    notes_json = canonical_json(validator_notes)

    cur = conn.cursor()
    cur.execute(
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
    conn.commit()
    return output_id
