"""Validate persisted code-graded exam proof before it can authorize permission."""

import json
import math
from typing import Any

from probation.config import Settings, settings
from probation.core.clock import timestamp_key
from probation.engine.exam_catalogue import operators_for_class


def meaningful_exam(row: Any, config: Settings | None = None) -> bool:
    cfg = config or settings
    try:
        details = json.loads(row["details_json"])
        from probation.llm.feature_identity import semantic_feature_version

        snapshot = details["snapshot"]
        required = details["required_operators"]
        coverage = details["operator_coverage"]
        base_ids = details["base_ids"]
        actual_operators = {op.name for op in operators_for_class(row["class_key"])}
        if (
            details["snapshot_version"] != "wp5-frozen-v1"
            or not snapshot["policy_digest"]
            or not snapshot["history_digest"]
            or snapshot["feature_version"]
            not in {semantic_feature_version(), semantic_feature_version(stub=True)}
            or snapshot["configured_models"] != [cfg.model_reader, cfg.model_exam_edits]
            or timestamp_key(snapshot["model_cutoff"]) > timestamp_key(snapshot["history_cutoff"])
            or timestamp_key(snapshot["history_cutoff"]) > timestamp_key(row["started_at"])
            or timestamp_key(row["started_at"]) > timestamp_key(row["finished_at"])
            or not isinstance(base_ids, list)
            or any(not isinstance(base, str) or not base for base in base_ids)
            or len(set(base_ids)) < cfg.exam_min_valid_cases
            or len(base_ids) != len(set(base_ids))
            or details["valid_base_cases"] != len(set(base_ids))
            or not actual_operators
            or set(required) != actual_operators
            or len(required) != len(actual_operators)
            or set(required) != set(coverage)
            or any(
                type(coverage[name]) is not int
                or not cfg.exam_min_valid_cases <= coverage[name] <= len(base_ids)
                for name in required
            )
            or details["pipeline_failures"] != 0
            or details["missing_operators"]
        ):
            return False
        for key, limit in (
            ("invariance_flip_rate", cfg.exam_invariance_max_flip),
            ("directional_violations_critical", cfg.exam_critical_max_violations),
            ("directional_violation_rate_other", cfg.exam_other_max_violation_rate),
        ):
            value = float(row[key])
            if not math.isfinite(value) or not 0 <= value <= limit:
                return False
        return True
    except (KeyError, IndexError, ValueError, TypeError):
        return False
