"""Bootstrap-only proposal extension for CONTRACT 8 authority-loss followups."""

import sqlite3


def migrate_followup_proposals(conn: sqlite3.Connection) -> None:
    """Join the lifecycle transaction; its caller disables/restores foreign keys.

    Keep every historical value and reference. The original proposal remains unique;
    only a separately linked followup can share its situation. Never rename the old
    table, which would rewrite child foreign keys to the temporary name.
    """
    if "followup_of_action_id" in {r[1] for r in conn.execute("PRAGMA table_info(proposals)")}:
        return
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name='proposals'").fetchone()
    if row is None:
        raise ValueError("Missing proposals schema")
    ddl = str(row[0])
    marker = "situation_id TEXT NOT NULL UNIQUE REFERENCES situations(id)"
    if marker not in ddl:
        raise ValueError("Unrecognized proposals schema; refusing destructive migration")
    ddl = ddl.replace("CREATE TABLE proposals", "CREATE TABLE d3_proposals_upgrade", 1)
    ddl = ddl.replace(marker, "situation_id TEXT NOT NULL REFERENCES situations(id)", 1)
    last = ddl.rfind(")")
    ddl = ddl[:last] + ", followup_of_action_id TEXT REFERENCES actions(id)\n" + ddl[last:]
    objects = [
        str(r[0])
        for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name='proposals' AND type IN('index','trigger') "
            "AND sql IS NOT NULL ORDER BY type,name"
        )
    ]
    conn.execute(ddl)
    columns = ",".join(str(r[1]) for r in conn.execute("PRAGMA table_info(proposals)"))
    conn.execute(f"INSERT INTO d3_proposals_upgrade ({columns}) SELECT {columns} FROM proposals")
    conn.execute("DROP TABLE proposals")
    conn.execute("ALTER TABLE d3_proposals_upgrade RENAME TO proposals")
    for statement in objects:
        conn.execute(statement)
    conn.execute(
        "CREATE UNIQUE INDEX d3_initial_proposal ON proposals(situation_id) WHERE followup_of_action_id IS NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX d3_followup_action ON proposals(followup_of_action_id) WHERE followup_of_action_id IS NOT NULL"
    )
