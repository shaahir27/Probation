"""Files pack deterministic clue extraction via HistoryView.

Authority: docs/PACKS_SPEC.md section 3.4.
Enforces Invariant I-6: History is read strictly through HistoryView(as_of=t).
"""

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import publicsuffix2

from probation.config import settings
from probation.core.clock import get_clock
from probation.core.history import HistoryView
from probation.core.types import Situation

EXTENSION_GROUPS = {
    "doc": frozenset({"pdf", "doc", "docx", "txt", "rtf", "odt", "md", "tex", "pages"}),
    "sheet": frozenset({"xls", "xlsx", "csv", "tsv", "numbers", "ods"}),
    "slide": frozenset({"ppt", "pptx", "key", "odp"}),
    "image": frozenset({"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "tiff", "heic"}),
    "archive": frozenset({"zip", "tar", "gz", "tgz", "bz2", "rar", "7z", "xz"}),
    "code": frozenset(
        {
            "py",
            "js",
            "ts",
            "jsx",
            "tsx",
            "html",
            "css",
            "java",
            "c",
            "cpp",
            "h",
            "go",
            "rs",
            "rb",
            "sh",
            "sql",
            "json",
            "yaml",
            "yml",
            "xml",
        }
    ),
    "audio_video": frozenset(
        {
            "mp4",
            "mkv",
            "avi",
            "mov",
            "wmv",
            "flv",
            "webm",
            "mp3",
            "wav",
            "m4a",
            "flac",
            "ogg",
            "aac",
        }
    ),
}

TOP_NAME_TOKENS = [
    "report",
    "assignment",
    "lecture",
    "lab",
    "notes",
    "project",
    "invoice",
    "receipt",
    "statement",
    "summary",
    "draft",
    "final",
    "review",
    "test",
    "exam",
    "homework",
    "slide",
    "presentation",
    "syllabus",
    "paper",
    "article",
    "resume",
    "cv",
    "letter",
    "doc",
    "sheet",
    "data",
    "code",
    "script",
    "build",
    "setup",
    "guide",
    "manual",
    "install",
    "patch",
    "update",
    "release",
    "log",
    "output",
    "result",
    "analysis",
    "figure",
    "table",
    "diagram",
    "schedule",
    "plan",
    "budget",
    "tax",
    "bill",
    "scan",
]


def extract_origin_group(origin_url: str | None) -> str:
    """Extract registrable domain from origin_url using offline public suffix list."""
    if not origin_url:
        return "unknown"
    clean_url = origin_url.strip()
    if not clean_url:
        return "unknown"
    try:
        parsed = urlparse(clean_url)
        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return "unknown"
        sld = publicsuffix2.get_sld(hostname)
        return str(sld).lower() if sld else hostname
    except Exception:
        return "unknown"


def extract_ext_group(ext: str | None) -> str:
    """Classify file extension into semantic group per PACKS_SPEC section 3.4."""
    if not ext:
        return "other"
    clean_ext = ext.lower().lstrip(".")
    for group_name, ext_set in EXTENSION_GROUPS.items():
        if clean_ext in ext_set:
            return group_name
    return "other"


def extract_size_bucket(size_bytes: int) -> str:
    """Buckets size: xs (<100KB), s (<1MB), m (<10MB), l (>=10MB)."""
    if size_bytes < 100 * 1024:
        return "xs"
    elif size_bytes < 1024 * 1024:
        return "s"
    elif size_bytes < 10 * 1024 * 1024:
        return "m"
    return "l"


def tokenize_name(name: str) -> set[str]:
    """Tokenize filename into alphanumeric tokens."""
    stem = Path(name).stem.lower()
    return set(re.findall(r"[a-z0-9]+", stem))


def extract_files_clues(
    s: Situation,
    hist: HistoryView,
    payload: dict[str, Any] | None = None,
) -> dict[str, float | str | bool]:
    """Compute 10 deterministic clues strictly through HistoryView (Invariant I-6)."""
    p = payload or {}
    filename = str(p.get("filename") or Path(p.get("rel_path", "document.pdf")).name)
    origin_url = p.get("origin_url")
    ext = str(p.get("ext") or Path(filename).suffix.lstrip("."))
    size_bytes = int(p.get("size_bytes") or p.get("size", 0))

    origin_group = extract_origin_group(origin_url)
    ext_group = extract_ext_group(ext)
    size_bucket = extract_size_bucket(size_bytes)

    # Time clues in USER_TZ
    tz = ZoneInfo(settings.user_tz)
    try:
        dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00")).astimezone(tz)
    except Exception:
        dt = get_clock().now(tz)

    hour_of_day = dt.hour
    weekday = dt.weekday()

    name_has_digits = bool(re.search(r"\d", filename))
    name_len = len(filename)

    # History queries strictly bounded by HistoryView(as_of=s.occurred_at)
    prior_sits = hist.get_situations(pack="files")
    prior_ids_for_origin: list[str] = []
    for sit_row in prior_sits:
        if sit_row["id"] == s.id:
            continue
        if sit_row["sender_key"] == origin_group:
            prior_ids_for_origin.append(sit_row["id"])

    n_prior_from_origin = len(prior_ids_for_origin)
    top_folder_for_origin = "none"
    top_folder_share = 0.0

    if prior_ids_for_origin:
        outcomes = hist.get_outcomes(situation_ids=prior_ids_for_origin)
        destinations: list[str] = []
        for o in outcomes:
            act = str(o["observed_action"])
            if act.startswith("MOVE_TO_FOLDER:"):
                dest = act.split("MOVE_TO_FOLDER:", 1)[1].strip()
                if dest:
                    destinations.append(dest)

        if destinations:
            counts = Counter(destinations)
            top_dest, top_count = counts.most_common(1)[0]
            top_folder_for_origin = top_dest
            top_folder_share = (top_count + 1.0) / (n_prior_from_origin + 2.0)
        else:
            top_folder_share = 1.0 / (n_prior_from_origin + 2.0)
    else:
        top_folder_share = 0.5  # Neutral Laplace smoothing: (0+1)/(0+2) = 0.5

    name_tokens = tokenize_name(filename)

    clues: dict[str, float | str | bool] = {
        "origin_group": origin_group,
        "ext_group": ext_group,
        "size_bucket": size_bucket,
        "name_has_digits": name_has_digits,
        "name_len": name_len,
        "hour_of_day": hour_of_day,
        "weekday": weekday,
        "n_prior_from_origin": n_prior_from_origin,
        "top_folder_for_origin": top_folder_for_origin,
        "top_folder_share": float(top_folder_share),
    }

    # Add 50 top name token features
    for token in TOP_NAME_TOKENS:
        clues[f"tok_{token}"] = token in name_tokens

    return clues
