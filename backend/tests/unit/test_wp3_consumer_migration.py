"""P09 migration boundaries: no ad hoc client can bypass registered transport."""

import ast
from pathlib import Path

from probation.engine.habits import validate_wording_sentence
from probation.eval.baselines import LLMConfidenceBaseline
from probation.packs.radar.digest import build_code_fallback_digest, validate_radar_digest


def test_wording_cannot_flip_action_or_scope_with_equal_numbers() -> None:
    template = "You archived 8 of 10 emails with sender=known."
    assert not validate_wording_sentence(
        template, "You replied to 8 of 10 emails with sender=known."
    )
    assert not validate_wording_sentence(
        template, "You never archived 8 of 10 emails with sender=known."
    )
    assert not validate_wording_sentence(
        template, "You archived 8 of 10 emails with sender=unknown."
    )


def test_digest_urls_require_exact_membership() -> None:
    entries = [{"n": 1, "title": "Event", "source_url": "https://official.test"}]
    assert not validate_radar_digest("[1] https://official.test.attacker.test", entries)[0]


def test_code_digest_respects_both_bounds() -> None:
    entries = [{"n": i, "title": "Word " * 70, "organiser": "Org " * 25} for i in range(8)]
    text = build_code_fallback_digest(entries)
    assert len(text) <= 700 and len(text.split()) <= 120


def test_missing_b3_is_not_an_autonomous_heuristic(basic_situation) -> None:
    result = LLMConfidenceBaseline(tau=0).predict(basic_situation)
    assert result.action == "ABSTAIN" and not result.is_autonomous
    assert "not_run" in " ".join(result.reasons)


def test_no_remaining_obsolete_dispatch_calls() -> None:
    root = Path(__file__).resolve().parents[2] / "src/probation"
    obsolete = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "complete_json":
                    obsolete.append(str(path.relative_to(root)))
    assert not obsolete
