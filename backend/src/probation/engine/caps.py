"""Hard-coded action autonomy caps, economic losses, and recallability.

Authority: docs/CONTRACT.md invariants I-10, I-20 and docs/ENGINE_SPEC.md section 8.
Autonomy caps and losses are strictly hard-coded in code and can never be overridden by LLMs or data.
"""

from typing import Final

from probation.core.types import ActionSpec

# Attention cost in units of utility (default 1)
ATTENTION_COST: Final[float] = 1.0

# Base action specification catalog: ActionSpec(type, recallable, base_cap, loss)
ACTION_CATALOG: Final[dict[str, ActionSpec]] = {
    # Email Action Family
    "ARCHIVE": ActionSpec(type="ARCHIVE", recallable=True, base_cap=3, loss=5.0),
    "TRASH": ActionSpec(type="TRASH", recallable=True, base_cap=2, loss=20.0),
    "REPLY": ActionSpec(type="REPLY", recallable=False, base_cap=2, loss=40.0),
    "FORWARD": ActionSpec(type="FORWARD", recallable=False, base_cap=1, loss=40.0),
    "LEAVE": ActionSpec(type="LEAVE", recallable=False, base_cap=0, loss=0.0),
    "STAR": ActionSpec(type="STAR", recallable=True, base_cap=3, loss=2.0),
    "LABEL": ActionSpec(type="LABEL", recallable=True, base_cap=3, loss=2.0),
    # Invite RSVP Family
    "ACCEPT": ActionSpec(type="ACCEPT", recallable=False, base_cap=2, loss=10.0),
    "DECLINE": ActionSpec(type="DECLINE", recallable=False, base_cap=2, loss=20.0),
    "TENTATIVE": ActionSpec(type="TENTATIVE", recallable=False, base_cap=2, loss=5.0),
    "NO_RESPONSE": ActionSpec(type="NO_RESPONSE", recallable=False, base_cap=0, loss=0.0),
    # File Destination Family
    "MOVE_TO_FOLDER": ActionSpec(type="MOVE_TO_FOLDER", recallable=True, base_cap=3, loss=5.0),
    # Chain Follow-up Family
    "BLOCK_TIME": ActionSpec(type="BLOCK_TIME", recallable=True, base_cap=3, loss=3.0),
    "CREATE_FOLDER": ActionSpec(type="CREATE_FOLDER", recallable=True, base_cap=3, loss=2.0),
    "CREATE_TASK": ActionSpec(type="CREATE_TASK", recallable=True, base_cap=3, loss=2.0),
    # Opportunity Triage Family (Radar)
    "TRACK": ActionSpec(type="TRACK", recallable=True, base_cap=3, loss=3.0),
    "DISMISS": ActionSpec(type="DISMISS", recallable=True, base_cap=2, loss=8.0),
    # Link Triage Family (Reading)
    "FILE_TO_COLLECTION": ActionSpec(
        type="FILE_TO_COLLECTION", recallable=True, base_cap=3, loss=3.0
    ),
    "ARCHIVE_LINK": ActionSpec(type="ARCHIVE_LINK", recallable=True, base_cap=2, loss=6.0),
}

# Base action caps lookup
BASE_ACTION_CAPS: Final[dict[str, int]] = {
    name: spec.base_cap for name, spec in ACTION_CATALOG.items()
}

# Losses lookup
ACTION_LOSSES: Final[dict[str, float]] = {name: spec.loss for name, spec in ACTION_CATALOG.items()}


def is_recallable(action: str) -> bool:
    """Return True if action is recallable (can be cleanly undone)."""
    spec = ACTION_CATALOG.get(action.upper())
    return spec.recallable if spec is not None else False


def get_action_loss(action: str) -> float:
    """Return economic loss of a wrong action."""
    spec = ACTION_CATALOG.get(action.upper())
    return spec.loss if spec is not None else 10.0


def get_economic_bar(action: str, attention_cost: float = ATTENTION_COST) -> float:
    """Return economic probability bar p* = 1 - attention_cost / loss."""
    loss = get_action_loss(action)
    if loss <= 0:
        return 1.0
    return max(0.0, 1.0 - (attention_cost / loss))


def get_conditional_cap(
    action: str,
    family: str | None = None,
    sender_tier: str | None = None,
    organizer_tier: str | None = None,
    money_involved: bool = False,
    asks_for_personal_info: bool = False,
    web_cap: int | None = None,
    hands_off_reason: str | None = None,
) -> int:
    """Evaluate context-dependent autonomy cap modifiers per ENGINE_SPEC.md section 8.1.

    Returns the minimum conditional cap applicable.
    """
    if hands_off_reason is not None:
        return 0

    caps: list[int] = [3]
    act = action.upper()

    # 1. Mail conditional caps
    if family == "email_action" or sender_tier is not None:
        if sender_tier == "unknown" or money_involved or asks_for_personal_info:
            if act in ("REPLY", "FORWARD", "TRASH"):
                caps.append(1)
            elif act == "ARCHIVE":
                caps.append(2)

    # 2. Calendar conditional caps
    if family == "invite_rsvp" or organizer_tier is not None:
        if organizer_tier == "unknown" or money_involved:
            if act in ("ACCEPT", "DECLINE", "TENTATIVE"):
                caps.append(1)

    # 3. Web veto (web_cap can only lower autonomy, CONTRACT I-21)
    if web_cap is not None:
        caps.append(web_cap)

    return min(caps)


def get_action_cap(
    action: str,
    family: str | None = None,
    sender_tier: str | None = None,
    organizer_tier: str | None = None,
    money_involved: bool = False,
    asks_for_personal_info: bool = False,
    web_cap: int | None = None,
    hands_off_reason: str | None = None,
    conditional_min: int = 3,
) -> int:
    """Return the effective upper bound autonomy cap for an action.

    Authority: docs/ENGINE_SPEC.md section 8:
    cap = min(base_action_cap, conditional_caps, web_cap).
    """
    if hands_off_reason is not None:
        return 0

    base = BASE_ACTION_CAPS.get(action.upper(), 0)
    cond = get_conditional_cap(
        action=action,
        family=family,
        sender_tier=sender_tier,
        organizer_tier=organizer_tier,
        money_involved=money_involved,
        asks_for_personal_info=asks_for_personal_info,
        web_cap=web_cap,
        hands_off_reason=hands_off_reason,
    )
    return min(base, cond, conditional_min)
