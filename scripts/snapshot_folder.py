"""Utility to take a deterministic snapshot manifest of a directory.

Authority: docs/PACKS_SPEC.md section 3.5.
"""

from pathlib import Path
import hashlib
import json
import sys
from typing import Dict, List


def hash_file(file_path: Path) -> str:
    """Compute sha256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def snapshot_folder(folder_path: str) -> List[Dict[str, str]]:
    """Generate list of file records with relative paths and content hashes."""
    root = Path(folder_path)
    records = []
    for item in sorted(root.rglob("*")):
        if item.is_file():
            records.append({
                "rel_path": str(item.relative_to(root).as_posix()),
                "size_bytes": str(item.stat().st_size),
                "content_hash": hash_file(item),
            })
    return records


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    results = snapshot_folder(target)
    print(json.dumps(results, indent=2))
