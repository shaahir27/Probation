#!/bin/sh
# Restore the synthetic demo workspace from demo/seed/. Refuses outside that profile.
set -eu

if [ "${APP_PROFILE:-}" != "synthetic" ]; then
  echo "refusing: APP_PROFILE must be synthetic" >&2
  exit 1
fi

DB="${DB_PATH:?DB_PATH is required}"
STORE="${PROBATION_GMAIL_STORE:?PROBATION_GMAIL_STORE is required}"
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SEED="$ROOT/demo/seed"

restore() {
  src="$1"
  dst="$2"
  if [ ! -f "$src" ]; then
    echo "refusing: missing $src" >&2
    exit 1
  fi
  mkdir -p "$(dirname -- "$dst")"
  tmp="$dst.reset.$$"
  cp "$src" "$tmp"
  mv "$tmp" "$dst"
  rm -f "$dst-wal" "$dst-shm"
}

restore "$SEED/engine.db" "$DB"
restore "$SEED/connector_store.db" "$STORE"
echo "restored synthetic demo workspace"
