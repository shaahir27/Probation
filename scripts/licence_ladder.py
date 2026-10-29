"""Print, per (class_key, action), the evidence held and what the next level needs."""

import os
import sys
from pathlib import Path

from scipy.stats import beta

REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from probation.config import settings
from probation.core.clock import operational_clock
from probation.db.connection import get_connection
from probation.engine.evidence import aggregate_evidence
from probation.engine.licence import derive_licences


def perfect_n(target: float) -> int:
    """Smallest perfect record whose 95% Beta lower bound clears target."""
    n = 1
    while beta.ppf(0.05, n + 1, 1) < target:
        n += 1
    return n


def main() -> None:
    as_of = sys.argv[1] if len(sys.argv) > 1 else operational_clock().now_iso()
    conn = get_connection(settings.db_path)
    try:
        stats = aggregate_evidence(conn, as_of, persist=False)
        levels = derive_licences(conn, as_of, stats=stats)
    finally:
        conn.close()
    need_l2, need_l3 = perfect_n(settings.l2_min_lb), perfect_n(settings.l3_min_lb)
    print(f"perfect record needed: L2 n>={need_l2}, L3 n>={need_l3}")
    print(f"{'class_key':38} {'action':9} {'n':>4} {'k':>4} {'lb':>6} {'lvl':>4}")
    for (ck, act), s in sorted(stats.items(), key=lambda kv: -kv[1].n_strong)[:20]:
        lvl = int(levels[(ck, act)].level) if (ck, act) in levels else 0
        print(f"{ck:38} {act:9} {s.n_strong:4} {s.k_strong:4} {s.lb_strong:6.3f} {lvl:4}")


if __name__ == "__main__":
    main()
