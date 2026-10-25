"""D5 read endpoints expose durable whole-population totals without provider calls."""

from probation.db.connection import ensure_schema, get_connection


def test_usage_totals_are_not_limited_to_display_page(tmp_path, monkeypatch):
    from probation.api.routes.webfacts import get_web_facts
    from probation.config import settings

    path = tmp_path / "usage.db"
    conn = get_connection(path)
    ensure_schema(conn)
    from probation.web.accounting import TavilyAccounting

    for n in range(55):
        accounting = TavilyAccounting(conn, run_id=f"synthetic-test-{n}")
        attempt = accounting.reserve(
            endpoint="search",
            purpose="vet_ident",
            query="public.example official website",
            params={},
            maximum_units=1000,
            situation_id=None,
        )
        accounting.dispatch(attempt)
        accounting.finish(
            attempt,
            usage=1000,
            ok=True,
            latency_ms=1,
            params={},
            endpoint="search",
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(settings, "db_path", path)
    result = get_web_facts()
    assert result["total_calls"] == 55 and result["total_credits"] == 55
    assert len(result["queries"]) == 50
    assert result["held_credits"] == 0 and result["unknown_attempts"] == 0
