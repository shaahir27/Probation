"""Explicitly selected synthetic D5 acceptance, fixed persistent allowance and namespace.

Run from the root checkout with D5 backend/src on PYTHONPATH. No environment file
is copied. Default invocation sends nothing. All HTTP stays in approved clients.
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

COHORT = (
    (
        "ordinary_request",
        "Synthetic agenda",
        "Please review the synthetic agenda and acknowledge receipt.",
        "request",
    ),
    (
        "newsletter",
        "Synthetic weekly newsletter",
        "This automated weekly newsletter contains fictional project news. No action is required.",
        "newsletter",
    ),
    (
        "money_request",
        "Synthetic reimbursement",
        "Please transfer INR 500 for this fictional workshop. Do not actually pay.",
        "request",
    ),
    (
        "personal_data_request",
        "Synthetic identity check",
        "Please share your password and bank account details for this fictional exercise. Do not actually share them.",
        "request",
    ),
    (
        "deadline",
        "Synthetic review deadline",
        "Please review the fictional draft by 28 October 2026 at 17:00 IST.",
        "request",
    ),
    (
        "opportunity",
        "NVIDIA Graduate Fellowship Program",
        "NVIDIA Graduate Fellowship Program is an opportunity for research students. Review the public application information. This is a synthetic invitation, not an offer. No application or payment is authorized.",
        "opportunity",
    ),
)
PRICE_SOURCE = (
    "https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference"
)
RUN_ID = "d5-nemotron-tavily"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("D5 provider acceptance requires explicit --allow-live")
    root = Path.cwd().resolve()
    if not (root / "data/d5/worktree/scripts/d5_live.py").is_file():
        parser.error("Run from the original project root; the allowance path is fixed")

    from probation.config import settings
    from probation.core.clock import Clock
    from probation.db.access import Role
    from probation.db.connection import (
        ensure_schema,
        get_connection,
        get_role_connection,
    )
    from probation.db.spend import SpendStore, default_lease_owner
    from probation.db.spend_types import provision_budget_scope
    from probation.llm.budget import (
        BudgetExceeded,
        BudgetGuard,
        load_price_table,
        units_to_usd,
        usd_to_units,
    )
    from probation.llm.catalog import resolve_job
    from probation.llm.client import LLMClient
    from probation.llm.consumers import RegisteredConsumer
    from probation.llm.context import build_request_context
    from probation.llm.errors import LLMValidationError
    from probation.llm.feature_identity import semantic_feature_version
    from probation.llm.gateway import JobFailure, JobGateway, transport_authority
    from probation.llm.generation import profile_version
    from probation.llm.writer import generate_reply
    from probation.web.accounting import accounting_summary
    from probation.web.client import TavilyClient
    from probation.web.verification import verify_email_opportunity

    if settings.llm_base_url.rstrip("/") != "https://api.tokenfactory.nebius.com/v1":
        raise ValueError("Unapproved Nebius endpoint")
    if settings.tavily_base_url.rstrip("/") != "https://api.tavily.com":
        raise ValueError("Unapproved Tavily endpoint")
    if not settings.llm_api_key or not settings.tavily_api_key:
        raise ValueError("Required application credentials unavailable")
    live = root / "data/d5/live"
    live.mkdir(parents=True, exist_ok=True)
    clock = Clock.live()
    started = clock.now_iso()
    cohort_bytes = json.dumps(COHORT, ensure_ascii=False).encode()
    cohort_path = live / "cohort.json"
    if cohort_path.exists() and cohort_path.read_bytes() != cohort_bytes:
        raise ValueError("Frozen cohort differs; do not reset the spend namespace")
    cohort_path.write_bytes(cohort_bytes)
    db_path = live / "accounting.db"
    bootstrap = get_connection(db_path)
    ensure_schema(bootstrap)
    price_path = root / "data/d5/worktree/config/prices.json"
    prices = load_price_table(price_path)
    price_version = hashlib.sha256(price_path.read_bytes()).hexdigest()
    configured = {
        settings.model_reader,
        settings.model_writer,
        settings.model_exam_edits,
    }
    catalog = {row["id"] for row in LLMClient().available_models()}
    if not {settings.model_reader, settings.model_writer} <= catalog:
        raise ValueError("Required configured model unavailable; no model substitution")
    for model in (settings.model_reader, settings.model_writer):
        if model not in prices:
            raise ValueError("Configured price unavailable")
        provision_budget_scope(
            bootstrap,
            provider="nebius_token_factory",
            account_label=RUN_ID,
            model_id=model,
            period_rule="total",
            period_key="total",
            cap_units=usd_to_units("1"),
            price_version=price_version,
            created_at_op=started,
        )
    connections = [
        get_role_connection(db_path, role) for role in (Role.BRAIN, Role.WEBFACTS)
    ]

    def consumer(conn: Any, role: str) -> RegisteredConsumer:
        client = LLMClient(
            budget_guard=BudgetGuard(limit_usd="1", price_table=prices),
            clock=clock,
            max_physical_attempts=3,
            max_retries=2,
            spend_store=SpendStore(
                conn,
                role=role,
                lease_owner=default_lease_owner(role),
                account_label=RUN_ID,
            ),
        )
        return RegisteredConsumer(
            JobGateway(client, conn=conn), transport_authority(client)
        )

    brain, web = (
        consumer(conn, role)
        for conn, role in zip(connections, ("brain", "webfacts"), strict=True)
    )
    manifest: dict[str, Any] = {
        "run_id": RUN_ID,
        "started_at": started,
        "cohort_sha256": hashlib.sha256(cohort_bytes).hexdigest(),
        "price_version": price_version,
        "price_source": PRICE_SOURCE,
        "configured_models": sorted(configured),
        "catalog_listed": sorted(configured & catalog),
        "ultra_status": "listed_not_inferred",
        "feature_version": semantic_feature_version(),
        "generation_profiles": {
            model: profile_version(model)
            for model in (settings.model_reader, settings.model_writer)
        },
        "limits": {"nebius_usd": 1, "tavily_credits": 20},
        "cases": [],
        "errors": [],
    }
    try:
        for label, subject, body, expected in COHORT:
            context = build_request_context(
                resolve_job("reader.mail", "v4"),
                {
                    "subject": subject,
                    "body": body,
                    "sender_domain_class": "corp",
                },
            )
            try:
                result = brain.run(context, purpose="d5_synthetic_cohort")
                repeated = brain.run(context, purpose="d5_synthetic_cohort")
                assert repeated.cache_hit and repeated.physical_attempts == 0
                manifest["cases"].append(
                    {
                        "case": label,
                        "expected_intent": expected,
                        "fields": dict(result.data),
                        "intent_matches": result.data.get("intent") == expected,
                        "cache_repeat_zero_dispatch": True,
                        "physical_attempts": result.physical_attempts,
                        "provenance": result.provenance.as_dict(),
                        "cost_units": result.cost_units,
                    }
                )
            except (
                BudgetExceeded,
                JobFailure,
                LLMValidationError,
                ValueError,
                OSError,
                sqlite3.Error,
                AssertionError,
            ) as exc:
                manifest["errors"].append(
                    {
                        "case": label,
                        "type": type(exc).__name__,
                        "code": str(getattr(exc, "code", "failed_closed")),
                    }
                )
        manifest["writer_cases"] = []
        # Distinct frozen eligible mails, never a renamed resend of a closed request.
        for index, situation_id in (
            (0, "d5-live-writer"),
            (4, "d5-live-writer-deadline"),
        ):
            writer = generate_reply(
                brain,
                incoming=COHORT[index][2],
                original_sender="sender@example.test",
                situation_id=situation_id,
                preview_warrants_reply=True,
            )
            manifest["writer"] = {
                "case": COHORT[index][0],
                "persistable": writer.persistable,
                "status": writer.status.value,
                "provenance": writer.provenance.as_dict(),
                "validation_notes": list(writer.validation_notes),
                "failure_code": writer.failure.value if writer.failure else None,
            }
            manifest["writer_cases"].append(manifest["writer"])
            if writer.persistable:
                break
        tavily = TavilyClient(
            conn=connections[1], clock=clock, run_id=RUN_ID, run_credit_limit=20
        )
        search = tavily.search("python.org official website", purpose="vet_ident")
        manifest["search"] = {
            key: search.get(key)
            for key in (
                "status",
                "attempt_id",
                "fetched_at",
                "credits",
                "usage_provenance",
                "error",
            )
        }
        opportunity_context = web.context(
            "reader.opportunity",
            {"subject": COHORT[-1][1], "body": COHORT[-1][2]},
            prompt_version="v2",
        )
        opportunity = web.run(opportunity_context, purpose="d5_opportunity_reader")
        names = {
            key: opportunity.data.get(key)
            for key in ("organiser_name", "opportunity_name")
        }
        source = (COHORT[-1][1] + " " + COHORT[-1][2]).casefold()
        if not all(
            isinstance(name, str) and name.casefold() in source
            for name in names.values()
        ):
            raise ValueError("Public opportunity fields unsupported")
        card = verify_email_opportunity(
            connections[1],
            tavily,
            web,
            organiser_name=names["organiser_name"],
            opportunity_name=names["opportunity_name"],
            clock=clock,
        )
        manifest["extract_card"] = card.model_dump()
        before_repeat = accounting_summary(bootstrap)["total_calls"]
        before_repeat_nebius = bootstrap.execute(
            "SELECT COUNT(*) FROM llm_attempts"
        ).fetchone()[0]
        repeated_card = verify_email_opportunity(
            connections[1],
            tavily,
            web,
            organiser_name=names["organiser_name"],
            opportunity_name=names["opportunity_name"],
            clock=clock,
        )
        manifest["extract_cache_repeat_zero_dispatch"] = (
            card.availability in {"validated", "partial"}
            and repeated_card.availability == card.availability
            and accounting_summary(bootstrap)["total_calls"] == before_repeat
            and bootstrap.execute("SELECT COUNT(*) FROM llm_attempts").fetchone()[0]
            == before_repeat_nebius
        )
    except (
        BudgetExceeded,
        JobFailure,
        LLMValidationError,
        ValueError,
        OSError,
        sqlite3.Error,
        AssertionError,
    ) as exc:
        manifest["errors"].append(
            {
                "type": type(exc).__name__,
                "code": str(getattr(exc, "code", "failed_closed")),
            }
        )
    finally:
        manifest["finished_at"] = clock.now_iso()
        card_status = manifest.get("extract_card", {}).get("availability")
        intent_matches = sum(
            case.get("intent_matches") is True for case in manifest["cases"]
        )
        manifest["acceptance"] = {
            "nemotron_readers": len(manifest["cases"]) == len(COHORT),
            "intent_smoke": len(manifest["cases"]) == len(COHORT)
            and intent_matches == len(COHORT),
            "nemotron_writer": bool(manifest.get("writer", {}).get("persistable")),
            "tavily_search": manifest.get("search", {}).get("status") == "ok",
            "extract": card_status in {"validated", "partial"},
            "extract_cache": bool(manifest.get("extract_cache_repeat_zero_dispatch")),
            "combined_gmail_browser": "pending_D4_D6",
        }
        manifest["tavily"] = accounting_summary(bootstrap)
        totals = bootstrap.execute(
            "SELECT state,estimate_units,charged_units,usage_provenance FROM llm_attempts"
        ).fetchall()
        spent = sum(
            int(row["charged_units"] or 0)
            for row in totals
            if row["state"] == "reconciled"
        )
        held = sum(
            int(row["estimate_units"])
            for row in totals
            if row["state"] in {"reserved", "dispatched", "ambiguous"}
        )
        manifest["nebius"] = {
            "attempts": len(totals),
            "charged_usd": str(units_to_usd(spent)),
            "held_usd": str(units_to_usd(held)),
            "estimated_attempts": sum(
                row["usage_provenance"] == "estimated" for row in totals
            ),
            "estimated_charge_usd": str(
                units_to_usd(
                    sum(
                        int(row["charged_units"] or 0)
                        for row in totals
                        if row["usage_provenance"] == "estimated"
                    )
                )
            ),
        }
        assert spent + held <= usd_to_units("1")
        assert (
            manifest["tavily"]["total_credits"] + manifest["tavily"]["held_credits"]
            <= 20
        )
        stamp = started.replace(":", "").replace(".", "")
        destination = live / f"manifest-{stamp}.json"
        destination.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for conn in connections:
            conn.close()
        bootstrap.close()
        print(
            json.dumps(
                {
                    "manifest": str(destination),
                    "intent_matches": intent_matches,
                    "intent_cases": len(manifest["cases"]),
                    "nebius": manifest["nebius"],
                    "tavily": manifest["tavily"],
                    "errors": len(manifest["errors"]),
                }
            )
        )
    return (
        0
        if not manifest["errors"]
        and all(
            value is True
            for key, value in manifest["acceptance"].items()
            if key != "combined_gmail_browser"
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
