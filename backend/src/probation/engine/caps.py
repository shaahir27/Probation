"""Hard-coded action autonomy caps.

Authority: docs/CONTRACT.md invariant I-10 and docs/ENGINE_SPEC.md section 8.
Autonomy caps are strictly hard-coded in code and can never be overridden by LLMs or data.
"""

from typing import Final

# Base action caps per action type (level 0..3)
BASE_ACTION_CAPS: Final[dict[str, int]] = {
    "TRASH": 3,
    "ARCHIVE": 3,
    "STAR": 3,
    "LABEL": 3,
    "MOVE_TO_FOLDER": 2,
    "REPLY": 2,
    "FORWARD": 1,
    "ACCEPT": 2,
    "DECLINE": 2,
    "TENTATIVE": 2,
    "BLOCK_TIME": 2,
    "CREATE_TASK": 2,
    "TRACK": 2,
    "DISMISS": 3,
    "FILE_TO_COLLECTION": 2,
    "ARCHIVE_LINK": 3,
}


def get_action_cap(action: str, conditional_min: int = 3) -> int:
    """Return the effective upper bound autonomy cap for an action.

    Computed as min(base_action_cap, conditional_min).
    """
    base = BASE_ACTION_CAPS.get(action, 0)
    return min(base, conditional_min)
