"""Operator helper: produce the environment variables required to run a live Gmail role.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 11, docs/D4_LIVE_TEST_MANIFEST.md section 9.
This script performs no network calls, opens no store, and writes no files. It formats the
OAuth refresh bundle into the single typed grant variable consumed by the runtime process.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parent.parent / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

from probation.connectors.credentials_state import ProvisionedGrant
from probation.connectors.types import CredentialRole


def build_env_vars(
    *,
    role: CredentialRole,
    connection_id: str,
    account: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    label: str = "PROBATION",
    forward_to: str | None = None,
) -> dict[str, str]:
    """Compute the runtime environment dictionary for one live role."""
    grant = ProvisionedGrant(role, connection_id, account, "cred-ref-operator")
    bundle = json.dumps(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )
    env: dict[str, str] = {
        "PROBATION_RUNTIME_LIVE": "1",
        "PROBATION_RUNTIME_GRANT": f"{connection_id}|{account}|cred-ref-operator",
        grant.env_name: bundle,
        "PROBATION_GMAIL_LABEL": label,
    }
    if forward_to:
        env["PROBATION_GMAIL_FORWARD_ALLOWLIST"] = forward_to.strip().lower()
    return env


def format_env(vars_dict: dict[str, str], syntax: str = "sh") -> str:
    lines: list[str] = []
    for key, val in vars_dict.items():
        if syntax in ("sh", "bash"):
            escaped = val.replace("'", "'\\''")
            lines.append(f"export {key}='{escaped}'")
        elif syntax in ("ps1", "powershell"):
            escaped = val.replace("`", "``").replace('"', '`"')
            lines.append(f'$env:{key} = "{escaped}"')
        elif syntax in ("cmd", "bat"):
            lines.append(f'set "{key}={val}"')
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=["read", "write"])
    parser.add_argument("--connection-id", required=True, help="Opaque connector connection id")
    parser.add_argument("--account", required=True, help="Operator Google email address")
    parser.add_argument("--client-id", required=True, help="Google Cloud OAuth Client ID")
    parser.add_argument("--client-secret", required=True, help="Google Cloud OAuth Client Secret")
    parser.add_argument("--refresh-token", required=True, help="Offline OAuth refresh token")
    parser.add_argument("--label", default="PROBATION", help="Cohort/routing label (default: PROBATION)")
    parser.add_argument("--forward-to", default=None, help="Allowlisted forward recipient email")
    parser.add_argument(
        "--shell",
        choices=["sh", "bash", "powershell", "ps1", "cmd", "bat"],
        default="sh",
        help="Target shell syntax for environment exports",
    )
    args = parser.parse_args(argv)

    env = build_env_vars(
        role=args.role,
        connection_id=args.connection_id,
        account=args.account,
        client_id=args.client_id,
        client_secret=args.client_secret,
        refresh_token=args.refresh_token,
        label=args.label,
        forward_to=args.forward_to,
    )
    print(format_env(env, syntax=args.shell))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
