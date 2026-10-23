"""Operator-only, at-most-one-attempt registered Nemotron smoke.

Requires separate endpoint/model/budget authorization. Never auto-run in acceptance.
Without --allow-live this script imports no application configuration and sends nothing.
"""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument(
        "--db",
        type=Path,
        help="Approved synthetic database with an operator-provisioned budget scope",
    )
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("Live smoke requires separate authorization and --allow-live")
    if args.db is None:
        parser.error("Provide --db for the approved synthetic smoke namespace")

    from probation.core.clock import elapsed_seconds
    from probation.db.connection import ensure_schema, get_connection
    from probation.db.spend import SpendStore, default_lease_owner
    from probation.llm.budget import BudgetExceeded
    from probation.llm.catalog import resolve_job
    from probation.llm.client import LLMClient
    from probation.llm.consumers import RegisteredConsumer
    from probation.llm.context import build_request_context
    from probation.llm.gateway import JobFailure, JobGateway, transport_authority
    from probation.llm.prompt_loader import PromptAssetError

    conn = get_connection(args.db)
    ensure_schema(conn)
    try:
        client = LLMClient(
            max_physical_attempts=1,
            max_retries=0,
            spend_store=SpendStore(
                conn, role="brain", lease_owner=default_lease_owner("brain")
            ),
        )
        consumer = RegisteredConsumer(
            JobGateway(client, conn=conn), transport_authority(client)
        )
        context = build_request_context(
            resolve_job("reader.mail", "v3"),
            {
                "subject": "Project meeting",
                "sender_domain_class": "other",
                "body": "Professor Fiction asks owner@example.test to review a synthetic project draft.",
            },
            display_names=["Professor Fiction"],
        )
        started = elapsed_seconds()
        result = consumer.run(context, purpose="authorized_operator_smoke")
        print(
            {
                "validated": True,
                "cache_hit": result.cache_hit,
                "physical_attempts": result.physical_attempts,
                "cost_units": result.cost_units,
                "seconds": elapsed_seconds() - started,
            }
        )
    except (BudgetExceeded, JobFailure, PromptAssetError) as exc:
        print({"validated": False, "reason": str(exc.code)})
        raise SystemExit(1) from None
    finally:
        conn.close()


if __name__ == "__main__":
    main()
