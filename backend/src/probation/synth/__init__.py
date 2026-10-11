"""Synthetic world package: Personas, habits DSL, generator, and renderers.

Authority: docs/EVALUATION_PLAN.md section 2 and docs/PACKS_SPEC.md section 6.
"""

from probation.synth.generator import SyntheticGenerator, generate_synthetic_world
from probation.synth.habits_dsl import (
    HabitRule,
    PersonaHabits,
    build_habits_for_persona,
    evaluate_habit,
)
from probation.synth.importers import (
    ImportResult,
    import_calendar,
    import_files,
    import_links,
    import_mail,
)
from probation.synth.personas import (
    Contact,
    Persona,
    WritingStyle,
    get_default_persona,
    get_persona,
    list_personas,
)
from probation.synth.render import render_files, render_ics, render_mbox
from probation.synth.world import SimWorld

__all__ = [
    "Contact",
    "HabitRule",
    "ImportResult",
    "Persona",
    "PersonaHabits",
    "SimWorld",
    "SyntheticGenerator",
    "WritingStyle",
    "build_habits_for_persona",
    "evaluate_habit",
    "generate_synthetic_world",
    "get_default_persona",
    "get_persona",
    "import_calendar",
    "import_files",
    "import_links",
    "import_mail",
    "list_personas",
    "render_files",
    "render_ics",
    "render_mbox",
]
