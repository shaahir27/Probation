"""Licence derivation and maintenance.

Authority: docs/ENGINE_SPEC.md sections 6.2, 6.3.
"""

from probation.core.enums import LicenceLevel


def derive_licence_level(
    n_strong: int,
    lb_strong: float,
    exam_ok: bool,
    current_level: int = 0,
) -> LicenceLevel:
    """Derive permissible autonomy level given evidence volume and exam pass status."""
    if n_strong >= 100 and lb_strong >= 0.98 and exam_ok:
        return LicenceLevel.DO_SILENTLY
    elif n_strong >= 50 and lb_strong >= 0.95 and exam_ok:
        return LicenceLevel.DO_WITH_UNDO
    elif n_strong >= 20 and lb_strong >= 0.70:
        return LicenceLevel.SUGGEST
    return LicenceLevel.WATCH
