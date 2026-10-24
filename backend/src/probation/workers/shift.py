"""Reconstruct the current bounded fitted policy for a scheduled shift check."""

import sqlite3

from probation.config import settings
from probation.core.history import HistoryView
from probation.engine.policy import Policy
from probation.engine.training import build_cohort, fit_cohort
from probation.llm.feature_identity import semantic_feature_version


def fit_shift_policy(conn: sqlite3.Connection, family: str, as_of: str) -> Policy:
    history = HistoryView(conn, as_of)
    policy = Policy(
        family,
        cold_start_min=settings.cold_start_min_situations,
        train_half_life_days=settings.train_half_life_days,
        files_topk=settings.files_topk_folders,
    )
    cohorts = [
        build_cohort(history, family, semantic_feature_version(stub=stub)) for stub in (False, True)
    ]
    # Choose one compatible recorded feature population; never mix semantic versions.
    cohort = max(cohorts, key=lambda item: len(item.rows))
    return fit_cohort(policy, cohort, as_of)
