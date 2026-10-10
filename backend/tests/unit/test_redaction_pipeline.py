"""Unit tests for local deterministic PII redaction pipeline.

Authority: docs/TEST_PLAN.md (T-REDACT) and docs/PROMPTS.md section 1.
"""

from probation.llm.redact import redact


def test_t_redact_email_and_upi_distinction() -> None:
    """T-REDACT: Differentiates standard RFC emails from UPI handles."""
    text = "Send mail to bob@example.com or pay via bob@okhdfcbank."
    res = redact(text)

    assert "<EMAIL_1>" in res.text
    assert "<UPI_1>" in res.text
    assert "bob@example.com" not in res.text
    assert "bob@okhdfcbank" not in res.text

    assert res.restore_map["<EMAIL_1>"] == "bob@example.com"
    assert res.restore_map["<UPI_1>"] == "bob@okhdfcbank"
    assert res.counts["email"] == 1
    assert res.counts["upi"] == 1


def test_t_redact_same_value_same_placeholder() -> None:
    """T-REDACT: Repeated occurrences of the same sensitive token get the identical placeholder."""
    text = "Contact alice@corp.test today. If unavailable, try alice@corp.test again."
    res = redact(text)

    assert res.counts["email"] == 1
    assert "<EMAIL_1>" in res.text
    assert "<EMAIL_2>" not in res.text
    assert res.text.count("<EMAIL_1>") == 2


def test_t_redact_phone_numbers() -> None:
    """T-REDACT: Redacts Indian mobile numbers and international numbers."""
    text = "Call me at +91 9876543210 or office at +1 (555) 234-5678."
    res = redact(text)

    assert "<PHONE_1>" in res.text
    assert "<PHONE_2>" in res.text
    assert "+91 9876543210" not in res.text
    assert "+1 (555) 234-5678" not in res.text
    assert res.counts["phone"] == 2


def test_t_redact_aadhaar_and_negative_longer_digit() -> None:
    """T-REDACT: Aadhaar 12-digit numbers are masked; 16-digit order numbers are NOT masked as Aadhaar."""
    text = "My Aadhaar is 1234 5678 9012. Order tracking number is 9876543210123456."
    res = redact(text)

    assert "<AADHAAR_1>" in res.text
    assert "1234 5678 9012" not in res.text
    assert "9876543210123456" in res.text  # Not Aadhaar
    assert res.counts["aadhaar"] == 1


def test_t_redact_pan_and_ifsc() -> None:
    """T-REDACT: Redacts Indian PAN card format and bank IFSC codes."""
    text = "PAN is ABCDE1234F and bank branch IFSC is HDFC0001234."
    res = redact(text)

    assert "<PAN_1>" in res.text
    assert "<IFSC_1>" in res.text
    assert "ABCDE1234F" not in res.text
    assert "HDFC0001234" not in res.text
    assert res.counts["pan"] == 1
    assert res.counts["ifsc"] == 1


def test_t_redact_credit_cards_luhn_check() -> None:
    """T-REDACT: Luhn-valid credit card numbers are masked; invalid numbers are preserved."""
    # Standard Luhn-valid test number (4532 0150 0000 0007: checksum 30)
    valid_card = "4532 0150 0000 0007"
    # Invalid card number (checksum 31)
    invalid_card = "4532 0150 0000 0008"

    text = f"Valid: {valid_card}, Invalid: {invalid_card}"
    res = redact(text)

    assert "<CARD_1>" in res.text
    assert valid_card not in res.text
    assert invalid_card in res.text
    assert res.counts["card"] == 1


def test_t_redact_url_classification() -> None:
    """T-REDACT: URLs are replaced with <URL:class> placeholders."""
    text = "Check http://cs.iitd.ac.in/courses and https://portal.company.com/login and https://gmail.com"
    res = redact(text)

    assert "<URL:edu>" in res.text
    assert "<URL:corp>" in res.text
    assert "<URL:freemail>" in res.text
    assert res.counts["url"] == 3


def test_t_redact_person_display_names() -> None:
    """T-REDACT: Display names passed from headers are masked throughout text."""
    text = "Hello Dr. Ramesh Rao, thank you for writing. Regards, Meena."
    res = redact(text, display_names=["Ramesh Rao", "Meena"])

    assert "<PERSON_1>" in res.text
    assert "<PERSON_2>" in res.text
    assert "Ramesh Rao" not in res.text
    assert "Meena" not in res.text


def test_t_redact_quoted_history_and_signature_stripping() -> None:
    """T-REDACT: Strips quoted email reply blocks and signature blocks."""
    body = (
        "Let us meet on Friday at 2 pm.\n\n"
        "-- \n"
        "Dr. Sharma\n"
        "Phone: +91 9999999999\n\n"
        "On Wed, Oct 14, 2026 at 10:00 AM Alice wrote:\n"
        "> Will you be available this week?\n"
        "> Let me know."
    )
    res = redact(body, profile="mail")

    assert "Let us meet on Friday at 2 pm." in res.text
    assert "Dr. Sharma" not in res.text
    assert "Alice wrote" not in res.text
    assert "> Will you be available" not in res.text
