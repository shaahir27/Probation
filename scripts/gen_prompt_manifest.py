"""Generate backend/src/probation/llm/prompts/catalog_manifest.json.

The manifest is what makes a prompt asset testable: every registered job must appear with the
hash of the bytes that will actually be sent and the fingerprint of the model that validates the
answer. Assets are never edited to match a manifest; regenerate and review the diff.

Usage: python scripts/gen_prompt_manifest.py [--check]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "backend" / "src" / "probation" / "llm" / "prompts"

sys.path.insert(0, str(ROOT / "backend" / "src"))

from probation.llm.catalog import JOBS  # noqa: E402
from probation.llm.prompt_loader import schema_fingerprint  # noqa: E402


def build() -> dict[str, object]:
    assets: dict[str, dict[str, object]] = {}
    for spec in sorted(JOBS.values(), key=lambda s: s.qualified_id):
        text = (PROMPTS / spec.asset).read_text(encoding="utf-8")
        assets[spec.qualified_id] = {
            "asset": spec.asset,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "schema_fingerprint": schema_fingerprint(spec.output_model()),
            "model_role": spec.model_role.value,
            "max_tokens": spec.max_tokens,
        }
    return {"version": "wp3-1", "assets": assets}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the manifest is stale")
    args = parser.parse_args()
    payload = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    target = PROMPTS / "catalog_manifest.json"
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != payload:
            print("prompt manifest is stale; run scripts/gen_prompt_manifest.py")
            return 1
        print("prompt manifest is current")
        return 0
    target.write_text(payload, encoding="utf-8", newline="\n")
    print(f"wrote {target} ({len(payload)} bytes, {len(build()['assets'])} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
