"""Training labels obey the canonical family catalog; no authority is granted."""


def valid_label(family: str, action: str) -> bool:
    from probation.core.actions import (
        FAMILY_ACTIONS,
        PARAMETER_ACTIONS,
        InvalidAction,
        parse_action,
    )

    try:
        parsed = parse_action(action)
        return (
            parsed.label == action
            and parsed.type in FAMILY_ACTIONS.get(family, frozenset())
            and parsed.type not in {"ABSTAIN", "NONE"}
            and (parsed.type not in PARAMETER_ACTIONS or parsed.parameter is not None)
        )
    except InvalidAction:
        return False
