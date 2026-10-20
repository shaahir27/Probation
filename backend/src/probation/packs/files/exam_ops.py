"""Files pack examination perturbation operators.

Authority: docs/PACKS_SPEC.md section 3.9 and docs/ENGINE_SPEC.md section 15.
"""

from typing import Any

from probation.core.types import ExamOperator

FILES_EXAM_OPERATORS = [
    ExamOperator(
        name="rename_trivial",
        engine="code",
        expectation="invariant",
        critical=False,
        validator_name="name_suffix_or_case",
    ),
    ExamOperator(
        name="size_jitter",
        engine="code",
        expectation="invariant",
        critical=False,
        validator_name="size_within_5_percent",
    ),
    ExamOperator(
        name="origin_unknown",
        engine="code",
        expectation="no_more_autonomous",
        critical=True,
        validator_name="never_seen_origin",
    ),
    ExamOperator(
        name="executable_extension",
        engine="code",
        expectation="no_more_autonomous",
        critical=True,
        validator_name="extension_is_exe",
    ),
    ExamOperator(
        name="double_extension",
        engine="code",
        expectation="no_more_autonomous",
        critical=True,
        validator_name="double_exe_extension",
    ),
    ExamOperator(
        name="misleading_name",
        engine="code",
        expectation="no_more_autonomous",
        critical=False,
        validator_name="invoice_prefix_added",
    ),
]


def apply_files_code_operator(
    operator_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply deterministic perturbation to a files payload."""
    mutated = dict(payload)
    name = str(mutated.get("name", "document.pdf"))
    ext = str(mutated.get("ext", ".pdf"))
    size = int(mutated.get("size", 10240))

    if operator_name == "rename_trivial":
        base = name.rsplit(".", 1)[0]
        mutated["name"] = f"{base}_v1{ext}"

    elif operator_name == "size_jitter":
        mutated["size"] = int(size * 1.03)

    elif operator_name == "origin_unknown":
        mutated["origin_url"] = "https://unseen-random-portal-999.example/download"
        mutated["origin_group"] = "unseen-random-portal-999.example"

    elif operator_name == "executable_extension":
        base = name.rsplit(".", 1)[0]
        mutated["name"] = f"{base}.exe"
        mutated["ext"] = ".exe"

    elif operator_name == "double_extension":
        mutated["name"] = f"{name}.exe"
        mutated["ext"] = ".exe"

    elif operator_name == "misleading_name":
        mutated["name"] = f"invoice_{name}"

    return mutated


def validate_files_operator_result(
    operator_name: str,
    original_payload: dict[str, Any],
    mutated_payload: dict[str, Any],
) -> bool:
    """Validate that files operator effect was correctly applied."""
    orig_name = str(original_payload.get("name", ""))
    mut_name = str(mutated_payload.get("name", ""))

    if operator_name == "rename_trivial":
        return mut_name != orig_name and "_v1" in mut_name

    elif operator_name == "size_jitter":
        orig_size = int(original_payload.get("size", 0))
        mut_size = int(mutated_payload.get("size", 0))
        if orig_size == 0:
            return True
        diff_pct = abs(mut_size - orig_size) / float(orig_size)
        return mut_size != orig_size and diff_pct <= 0.05

    elif operator_name == "origin_unknown":
        mut_origin = str(mutated_payload.get("origin_url", ""))
        orig_origin = str(original_payload.get("origin_url", ""))
        return mut_origin != orig_origin and "unseen-random-portal-999.example" in mut_origin

    elif operator_name == "executable_extension":
        return mut_name.endswith(".exe") and not mut_name.endswith(".pdf.exe")

    elif operator_name == "double_extension":
        return mut_name.endswith(".exe") and any(
            mut_name.endswith(f"{e}.exe") for e in [".pdf", ".doc", ".docx", ".zip", ".png"]
        )

    elif operator_name == "misleading_name":
        return mut_name.startswith("invoice_")

    return True
