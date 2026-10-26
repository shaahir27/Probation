"""Set worker isolation markers before importing any application module.

This file intentionally uses only the standard library: importing ``probation.config`` first
would construct Settings and might read the checkout's dotenv file.
"""

import argparse
import os
import runpy
import sys
from collections.abc import Sequence

_ROLES = frozenset({"observation", "brain", "resolver", "examiner", "webfacts", "api", "executor"})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probation-worker-bootstrap")
    parser.add_argument("--role", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.role not in _ROLES:
        parser.error("invalid worker role")
    # Both markers are installed before any application import, so the first Settings build is
    # already a worker build: no dotenv path is consulted, and none is even configured here.
    os.environ["PROBATION_WORKER_ROLE"] = args.role
    os.environ.pop("PROBATION_ENV_FILE", None)
    os.environ["DB_PATH"] = args.db
    child_args = list(args.args)
    if child_args[:1] == ["--"]:
        child_args.pop(0)
    sys.argv = [args.module, *child_args]
    runpy.run_module(args.module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
