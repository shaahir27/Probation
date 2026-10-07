"""Database package: Connection management, access helpers, and tamper-evident ledger.

Authority: docs/DATA_MODEL.md and docs/CONTRACT.md section 3.
"""

from probation.db.connection import get_connection, init_db
from probation.db.ledger import append_ledger, verify_ledger

__all__ = [
    "append_ledger",
    "get_connection",
    "init_db",
    "verify_ledger",
]
