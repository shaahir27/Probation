"""Test T-CAPS and T-HANDSOFF: Hardcoded action caps, losses, economic bars, and hands-off safety rules.

Authority: docs/CONTRACT.md I-10, I-20, docs/ENGINE_SPEC.md section 8, and docs/TEST_PLAN.md.
"""

from probation.engine.caps import (
    BASE_ACTION_CAPS,
    get_action_cap,
    get_action_loss,
    get_conditional_cap,
    get_economic_bar,
    is_recallable,
)
from probation.engine.handsoff import is_hands_off


def test_t_caps_base_catalog() -> None:
    """Verify base caps, losses, recallable flags, and economic bars match ENGINE_SPEC.md section 8."""
    # Expected table: (action, base_cap, loss, recallable, bar_p_star)
    expected = [
        ("ARCHIVE", 3, 5.0, True, 0.800),
        ("TRASH", 2, 20.0, True, 0.950),
        ("REPLY", 2, 40.0, False, 0.975),
        ("FORWARD", 1, 40.0, False, 0.975),
        ("LEAVE", 0, None, False, None),
        ("ACCEPT", 2, 10.0, False, 0.900),
        ("DECLINE", 2, 20.0, False, 0.950),
        ("TENTATIVE", 2, 5.0, False, 0.800),
        ("NO_RESPONSE", 0, None, False, None),
        ("MOVE_TO_FOLDER", 3, 5.0, True, 0.800),
        ("BLOCK_TIME", 3, 3.0, True, 0.667),
        ("CREATE_FOLDER", 3, 2.0, True, 0.500),
        ("CREATE_TASK", 3, 2.0, True, 0.500),
        ("TRACK", 3, 3.0, True, 0.667),
        ("DISMISS", 2, 8.0, True, 0.875),
    ]

    for act, exp_cap, exp_loss, exp_rec, exp_bar in expected:
        assert BASE_ACTION_CAPS[act] == exp_cap, (
            f"Cap mismatch for {act}: got {BASE_ACTION_CAPS[act]}, expected {exp_cap}"
        )
        assert is_recallable(act) == exp_rec, (
            f"Recallable mismatch for {act}: got {is_recallable(act)}, expected {exp_rec}"
        )

        if exp_loss is not None:
            assert get_action_loss(act) == exp_loss, f"Loss mismatch for {act}"
        if exp_bar is not None:
            assert abs(get_economic_bar(act) - exp_bar) <= 0.001, f"Bar mismatch for {act}"

        # Invariant I-20: Level 3 impossible for non-recallable actions
        if not exp_rec:
            assert exp_cap <= 2, f"Non-recallable action {act} has base cap > 2!"


def test_t_caps_conditional_caps() -> None:
    """Verify conditional caps combine with min across mail, calendar, and web veto."""
    # 1. Unknown mail sender -> REPLY, FORWARD, TRASH cap 1; ARCHIVE cap 2
    assert get_conditional_cap("REPLY", family="email_action", sender_tier="unknown") == 1
    assert get_conditional_cap("FORWARD", family="email_action", sender_tier="unknown") == 1
    assert get_conditional_cap("TRASH", family="email_action", sender_tier="unknown") == 1
    assert get_conditional_cap("ARCHIVE", family="email_action", sender_tier="unknown") == 2

    # 2. Money involved in mail -> cap lowered
    assert get_conditional_cap("REPLY", family="email_action", money_involved=True) == 1
    assert get_conditional_cap("ARCHIVE", family="email_action", money_involved=True) == 2

    # 3. Personal info request in mail -> cap lowered
    assert get_conditional_cap("TRASH", family="email_action", asks_for_personal_info=True) == 1

    # 4. Unknown invite organizer or money involved -> ACCEPT/DECLINE cap 1
    assert get_conditional_cap("ACCEPT", family="invite_rsvp", organizer_tier="unknown") == 1
    assert get_conditional_cap("DECLINE", family="invite_rsvp", money_involved=True) == 1

    # 5. Web veto (web_cap = 1) -> caps all actions to 1
    assert get_conditional_cap("ARCHIVE", family="email_action", web_cap=1) == 1
    assert get_conditional_cap("BLOCK_TIME", family="chain_followup", web_cap=1) == 1

    # 6. Combined with min
    # ARCHIVE base cap 3, sender unknown gives 2, web_cap gives 1 -> min is 1
    cap = get_action_cap(
        "ARCHIVE",
        family="email_action",
        sender_tier="unknown",
        web_cap=1,
    )
    assert cap == 1


def test_t_handsoff_extensions_and_rlo() -> None:
    """Verify all blocked extensions, double extensions, and RLO character trigger hands-off."""
    # 1. Explicit dangerous extensions
    blocked_exts = [
        "exe",
        "msi",
        "bat",
        "cmd",
        "com",
        "scr",
        "js",
        "jse",
        "vbs",
        "vbe",
        "wsf",
        "ps1",
        "jar",
        "apk",
        "dmg",
        "pkg",
        "app",
        "lnk",
        "iso",
        "img",
        "dll",
        "sys",
    ]
    for ext in blocked_exts:
        filename = f"payload.{ext}"
        reason = is_hands_off(filename=filename)
        assert reason is not None, f"Extension .{ext} was NOT blocked!"
        assert "executable" in reason.lower() or "blocked" in reason.lower()

    # 2. Double extensions, e.g. document.pdf.exe
    double_ext_reason = is_hands_off(filename="financial_report.pdf.exe")
    assert double_ext_reason is not None
    assert "double extension" in double_ext_reason.lower()

    # 3. Unicode Right-to-Left Override character (\u202e)
    rlo_filename = "document\u202epdf.exe"
    rlo_reason = is_hands_off(filename=rlo_filename)
    assert rlo_reason is not None
    assert "right-to-left override" in rlo_reason.lower()

    # 4. Safe files should not be blocked (including scripts .py, .sh, .pyw)
    safe_files = [
        "statement.pdf",
        "data.csv",
        "notes.txt",
        "photo.png",
        "archive.tar.gz",
        "solution.py",
        "run_eval.sh",
        "tool.pyw",
    ]
    for safe in safe_files:
        assert is_hands_off(filename=safe) is None, f"Safe file {safe} was falsely blocked!"


def test_t_caps_fail_closed_unknown_actions() -> None:
    """H6 & H8: Invariant check verifies all packs default unknown action caps to 0 (fail closed)."""
    from probation.core.types import Features, Situation
    from probation.packs.calendar import CalendarPack
    from probation.packs.chains import ChainsPack
    from probation.packs.files import FilesPack
    from probation.packs.mail import MailPack
    from probation.packs.radar import RadarPack
    from probation.packs.reading import ReadingPack

    sit = Situation(
        id="sit-test",
        raw_item_id="raw-1",
        pack="mail",
        family="email_action",
        variant="",
        occurred_at="2026-05-01T10:00:00Z",
        sender_key="prof@college.edu",
        content_hash="abc",
        redacted_text="Test situation",
        created_at="2026-05-01T10:00:00Z",
    )
    feat = Features(
        situation_id="sit-test",
        deterministic={},
        reader_ok=True,
        reader={},
        featurizer_version="v1",
        features_hash="hash-1",
    )

    # Engine base cap lookup
    assert get_action_cap("COMPLETELY_UNKNOWN_ACTION") == 0

    # Pack level_cap implementations
    assert MailPack().level_cap("NONEXISTENT_MAIL_ACTION", sit, feat) == 0
    assert CalendarPack().level_cap("NONEXISTENT_CAL_ACTION", sit, feat) == 0
    assert FilesPack().level_cap("NONEXISTENT_FILE_ACTION", sit, feat) == 0
    assert ChainsPack().level_cap("NONEXISTENT_CHAIN_ACTION", sit, feat) == 0
    assert RadarPack().level_cap("NONEXISTENT_RADAR_ACTION", sit, feat) == 0
    assert ReadingPack().level_cap("NONEXISTENT_READING_ACTION", sit, feat) == 0


def test_t_otp_word_boundaries() -> None:
    """P2: Verify word boundary matching prevents false positives for 'otp'."""
    from probation.packs.mail import MailPack
    from probation.packs.mail.exam_ops import validate_mail_operator_result

    mail_pack = MailPack()

    # Substrings containing 'otp' inside other words should NOT trigger hands-off
    safe_texts = [
        "Please inspect the prototype design before the meeting.",
        "We are meeting for a hotpot dinner tonight.",
        "Follow the footpath along the river.",
        "Check the bootprint evidence from the lab.",
    ]
    for text in safe_texts:
        assert mail_pack.hands_off_text(text) is None, f"False positive on safe text: {text}"

    # Genuine OTP mentions should trigger
    sensitive_texts = [
        "Your login OTP is 482910.",
        "Please enter the one-time OTP sent to your phone.",
    ]
    for text in sensitive_texts:
        assert mail_pack.hands_off_text(text) is not None, f"Failed to detect OTP in: {text}"

    # Exam operator add_personal_info_request validation
    assert (
        validate_mail_operator_result("add_personal_info_request", "orig", "Here is the prototype.")
        is False
    )
    assert (
        validate_mail_operator_result("add_personal_info_request", "orig", "Please send your OTP.")
        is True
    )
