"""Core enumeration definitions.

Authority: docs/CONTRACT.md section 4 and docs/DATA_MODEL.md.
"""

from enum import IntEnum, StrEnum


class LicenceLevel(IntEnum):
    """Autonomy licence level for a (class_key, action) pair."""

    WATCH = 0
    SUGGEST = 1
    DO_WITH_UNDO = 2
    DO_SILENTLY = 3


class GateDecision(StrEnum):
    """Autonomous execution decision computed by the deterministic gate."""

    SHADOW = "SHADOW"
    SUGGEST = "SUGGEST"
    ASK = "ASK"
    HOLD_THEN_EXECUTE = "HOLD_THEN_EXECUTE"
    EXECUTE_UNDO = "EXECUTE_UNDO"
    EXECUTE_SILENT = "EXECUTE_SILENT"
    EXECUTE_IMMEDIATELY = "EXECUTE_SILENT"  # Alias for compatibility


Gate = GateDecision


class ActionStatus(StrEnum):
    """Lifecycle status of an executor action."""

    PENDING = "PENDING"
    HELD = "HELD"
    DONE = "DONE"
    UNDONE = "UNDONE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class EvidenceStrength(StrEnum):
    """Reliability tier of observed outcome."""

    STRONG = "STRONG"
    WEAK = "WEAK"


Strength = EvidenceTier = EvidenceStrength


class LedgerKind(StrEnum):
    """Event kind in the hash-chained ledger."""

    PROPOSAL = "proposal"
    OUTCOME = "outcome"
    ACTION = "action"
    USER_RESPONSE = "user_response"
    LICENCE_CHANGE = "licence_change"
    EXAM_RUN = "exam_run"
    DRIFT_ALARM = "drift_alarm"
    AUDIT_DRAW = "audit_draw"


class UserResponseKind(StrEnum):
    """Explicit response options provided by the user."""

    ACCEPT = "accept"
    REJECT = "reject"
    EDIT = "edit"
    UNDO = "undo"


class AlarmType(StrEnum):
    """Statistical drift alarm types."""

    CUSUM = "CUSUM"
    PSI = "PSI"
    FAMILY_SHIFT = "FAMILY_SHIFT"


class ClockMode(StrEnum):
    """Runtime clock mode."""

    REPLAY = "replay"
    LIVE = "live"
