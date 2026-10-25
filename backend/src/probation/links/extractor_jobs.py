"""Strict quarantine jobs over already stored pages; no Search/Extract transport.

WP7 owns official-source provenance and network authorization. A stored page here is
untrusted text, never a licence to fetch its links or expose it to a writer.
"""

import hashlib
import re
import sqlite3
from typing import Any, Literal

from probation.config import settings
from probation.core.clock import Clock, parse_timestamp
from probation.db.access import Role, RoleAccess
from probation.links.quarantine import (
    record_quarantine_output,
    validate_link_fields,
    validate_opportunity_fields,
)
from probation.llm.consumers import RegisteredConsumer
from probation.llm.gateway import JobFailure
from probation.llm.prompt_loader import PromptAssetError


def extract_stored_page(
    access: RoleAccess,
    consumer: RegisteredConsumer,
    *,
    extraction_id: str,
    kind: Literal["opportunity", "link"],
    clock: Clock,
) -> dict[str, Any]:
    if access.role is not Role.WEBFACTS:
        raise PermissionError("Only webfacts may run the quarantined page jobs")
    row = access.conn.execute("SELECT * FROM extractions WHERE id=?", (extraction_id,)).fetchone()
    if row is None or not row["ok"]:
        return {"ok": False, "reason": "extraction_unavailable", "fields": {}}
    now = clock.now()
    if not parse_timestamp(row["fetched_at"]) <= now < parse_timestamp(row["ttl_until"]):
        return {"ok": False, "reason": "extraction_outside_cutoff", "fields": {}}
    page = str(row["content_text"])
    if hashlib.sha256(page.encode()).hexdigest() != row["content_hash"]:
        return {"ok": False, "reason": "extraction_hash_mismatch", "fields": {}}
    try:
        result = consumer.call(
            f"extract.{kind}",
            {"page": page[: settings.quarantine_max_input_chars]},
            purpose="quarantined_extract",
        )
    except (JobFailure, PromptAssetError) as exc:
        return {"ok": False, "reason": exc.code.value, "fields": {}}
    fields = dict(result.data)
    validator = validate_opportunity_fields if kind == "opportunity" else validate_link_fields
    fields, ok, notes = validator(fields, page)
    # Titles/organisers need literal source support as well as a valid output shape.
    spans = {}
    for key in ("title", "organiser"):
        value = fields.get(key)
        if isinstance(value, str) and value:
            start = page.casefold().find(value.casefold())
            if start < 0:
                fields[key] = None
                ok = False
                notes.append(f"{key}_unsupported")
            else:
                spans[key] = [start, start + len(value)]
    # The schema has a bool, not a three-way fee fact. Preserve uncertainty explicitly.
    fee_status = "unknown"
    if kind == "opportunity":
        if re.search(
            r"\b(?:fee|cost)\s*(?:is|:)?\s*(?:[$₹€£]|INR\s*|Rs\.?\s*)?[1-9]\d*|\bpay\s*[$₹€£][1-9]\d*",
            page,
            re.I,
        ):
            fee_status = "payment_mentioned"
        elif re.search(
            r"\b(?:free of charge|no registration fee|registration is free)\b", page, re.I
        ):
            fee_status = "explicit_free"
    provenance = result.provenance.as_dict()
    try:
        with access.transaction():
            record_quarantine_output(
                access,
                extraction_id,
                result.provenance.prompt_id,
                result.provenance.prompt_version,
                result.provenance.model_id or "",
                fields,
                ok,
                [str(note).split(":", 1)[0] for note in notes],
                clock.now_iso(),
            )
    except (sqlite3.Error, ValueError):
        return {"ok": False, "reason": "quarantine_output_persistence_failed", "fields": {}}
    return {
        "ok": ok,
        "fields": fields,
        "fee_status": fee_status,
        "notes": [str(note).split(":", 1)[0] for note in notes],
        "source_url": row["url_norm"],
        "extraction_id": extraction_id,
        "content_hash": row["content_hash"],
        "support_spans": spans,
        "fetched_at": row["fetched_at"],
        "ttl_until": row["ttl_until"],
        "provenance": provenance,
    }
