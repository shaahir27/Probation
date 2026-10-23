"""Pure filename tokenization shared by pack and fold-local vocabulary."""

import re
from pathlib import Path


def tokenize_name(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", Path(name).stem.lower()))
