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
    HOLD_THEN_EXECUTE = "HOLD_THEN_EXECUTE"
    EXECUTE_IMMEDIATELY = "EXECUTE_IMMEDIATELY"
    ASK = "ASK"


class EvidenceTier(StrEnum):
    """Reliability tier of observed outcome."""

    STRONG = "STRONG"
    WEAK = "WEAK"


class AlarmType(StrEnum):
    """Statistical drift alarm types."""

    CUSUM = "CUSUM"
    PSI = "PSI"
    FAMILY_SHIFT = "FAMILY_SHIFT"


class ClockMode(StrEnum):
    """Runtime clock mode."""

    REPLAY = "replay"
    LIVE = "live"
