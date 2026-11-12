#!/usr/bin/env bash
# Stop everything started by run_all.sh
#
#   ./stop_all.sh                  stop the processes; keep edge results that are still waiting to be uploaded
#   ./stop_all.sh quiet            the same without output (run_all.sh calls this)
#   ./stop_all.sh --clear-queues   also delete every edge outbox row, including PENDING results (they are lost)
#   ./stop_all.sh --purge-sqs      also purge the SQS queue in NIMBUS_SQS_QUEUE_URL (shared by every edge cluster)
#
# Processes: the PIDs run_all.sh wrote to logs/pids, and their child processes, are stopped first. A leftover
# server.py / edge/run_supervisor.py / simulation/lite/viewer.py (run by python), Gazebo (`ign gazebo`) or
# ros_gz_bridge / ros_gz_image process is stopped only when it belongs to this checkout: its environment carries this
# checkout's DATA_DIR (run_all.sh exports it before starting anything) or its working directory is inside this
# checkout. Where that cannot be checked (no /proc and no lsof), only the PID file is used.
cd "$(dirname "$0")"
ROOT="$PWD"
LOGS="${LOGS_DIR:-logs}"
DATA="${DATA_DIR:-$ROOT/data}"

QUIET=0 CLEAR_QUEUES=0 PURGE_SQS=0
for arg in "$@"; do
  case "$arg" in
    quiet) QUIET=1 ;;
    --clear-queues) CLEAR_QUEUES=1 ;;
    --purge-sqs) PURGE_SQS=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "usage: $0 [quiet] [--clear-queues] [--purge-sqs]" >&2; exit 2 ;;
  esac
done
say() { [ "$QUIET" = 1 ] || echo "$@"; }
warn() { [ "$QUIET" = 1 ] || echo "$@" >&2; }

# --- processes ---------------------------------------------------------------------------------------------------

ownership_checkable() { [ -d "/proc/$$" ] || command -v lsof >/dev/null 2>&1; }

# True when process $1 was started from this checkout (see the header).
owned_here() {
  local pid="$1" cwd=""
  if [ -r "/proc/$pid/environ" ] && tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -Fqx "DATA_DIR=$DATA"; then
    return 0
  fi
  if [ -e "/proc/$pid/cwd" ]; then
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)"
  elif command -v lsof >/dev/null 2>&1; then
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  fi
  [ -n "$cwd" ] && { [ "$cwd" = "$ROOT" ] || [ "${cwd#"$ROOT"/}" != "$cwd" ]; }
}

# Child processes of $1, deepest first.
descendants() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do
    descendants "$child"
    echo "$child"
  done
}

TARGETS=()
add_target() { [ "$1" = "$$" ] || [ "$1" = "$PPID" ] || TARGETS+=("$1"); }

if [ -f "$LOGS/pids" ]; then
  while read -r p; do
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || continue
    # A PID from an earlier run may since have been reused by an unrelated process.
    if ownership_checkable && ! owned_here "$p"; then continue; fi
    for c in $(descendants "$p"); do add_target "$c"; done
    add_target "$p"
  done < "$LOGS/pids"
  : > "$LOGS/pids"
fi

# Leftovers not in the PID file (e.g. an earlier run's PID file was overwritten). Only with LOGS_DIR unset:
# run_all.sh sets it when it cleans up its own previous run.
if [ -z "${LOGS_DIR:-}" ] && ownership_checkable; then
  pattern='^([^ ]*/)?python3?(\.[0-9]+)? (-u )?([^ ]*/)?(server\.py|edge/run_supervisor\.py|simulation/lite/viewer\.py)( |$)|ign gazebo|ros_gz_bridge|ros_gz_image'
  for p in $(pgrep -f -- "$pattern" 2>/dev/null); do
    owned_here "$p" || continue
    for c in $(descendants "$p"); do add_target "$c"; done
    add_target "$p"
  done
fi

if [ "${#TARGETS[@]}" -gt 0 ]; then
  kill -TERM "${TARGETS[@]}" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    alive=()
    for p in "${TARGETS[@]}"; do kill -0 "$p" 2>/dev/null && alive+=("$p"); done
    [ "${#alive[@]}" -eq 0 ] && break
    sleep 0.5
  done
  [ "${#alive[@]}" -gt 0 ] && kill -KILL "${alive[@]}" 2>/dev/null
fi

# --- queues (only after the processes above have stopped) --------------------------------------------------------

# The file-backed cloud's cloud -> edge publications (leases, renewals, notices). A clean restart must not replay a
# lease publication left by a previous local-cloud run; the decision log and the edge's lease-version fence are kept.
cleared_cloud=0
if [ -f "$DATA/outbox.jsonl" ]; then
  cleared_cloud=$(awk 'NF { n++ } END { print n+0 }' "$DATA/outbox.jsonl")
  : > "$DATA/outbox.jsonl"
fi

# Edge SQLite outbox: edge -> cloud store-and-forward traffic, including OUTPUT_READY results that still have to be
# uploaded. By default only rows already delivered (status UPLOADED) are deleted; PENDING rows are sent when the edge
# starts again. --clear-queues deletes every row. leases, lease_versions and seen_messages are never touched: they
# are the replay fence for a deployed cloud whose outbox this machine cannot purge.
PY="$(command -v python3 || command -v python)"
deleted_edge=0 pending_edge=0
for db in "$DATA"/edge_*.db "$ROOT"/edge_*.db; do
  [ -f "$db" ] && [ -n "$PY" ] || continue
  read -r d k < <("$PY" - "$db" "$CLEAR_QUEUES" <<'PY'
import sqlite3
import sys

db, clear_all = sys.argv[1], sys.argv[2] == "1"
try:
    with sqlite3.connect(db) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbox'").fetchone():
            print(0, 0)
        else:
            where = "" if clear_all else " WHERE status = 'UPLOADED'"
            deleted = conn.execute("DELETE FROM outbox" + where).rowcount
            pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'PENDING'").fetchone()[0]
            print(deleted, pending)
except sqlite3.Error:
    print(0, 0)
PY
)
  d="${d//[!0-9]/}"; k="${k//[!0-9]/}"   # drop a stray CR (Windows Python)
  deleted_edge=$((deleted_edge + ${d:-0})); pending_edge=$((pending_edge + ${k:-0}))
done

# SQS is shared by every cluster of a deployment, so it is purged only on request.
if [ -n "${NIMBUS_SQS_QUEUE_URL:-}" ]; then
  if [ "$PURGE_SQS" = 1 ]; then
    if ! command -v aws >/dev/null 2>&1; then
      warn "warning: --purge-sqs given but the AWS CLI is unavailable"
    elif aws sqs purge-queue --queue-url "$NIMBUS_SQS_QUEUE_URL" --region "${AWS_REGION:-ap-south-1}" >/dev/null 2>&1; then
      say "purged SQS queue $NIMBUS_SQS_QUEUE_URL"
    else
      warn "warning: could not purge SQS queue $NIMBUS_SQS_QUEUE_URL"
    fi
  else
    say "left SQS queue $NIMBUS_SQS_QUEUE_URL untouched (pass --purge-sqs to purge it)"
  fi
elif [ "$PURGE_SQS" = 1 ]; then
  warn "warning: --purge-sqs given but NIMBUS_SQS_QUEUE_URL is not set"
fi

say "cloud outbox: cleared $cleared_cloud message(s)"
if [ "$CLEAR_QUEUES" = 1 ]; then
  say "edge outbox: deleted $deleted_edge row(s) (--clear-queues)"
else
  say "edge outbox: deleted $deleted_edge delivered row(s), kept $pending_edge pending (--clear-queues deletes them)"
fi
say "stopped ${#TARGETS[@]} process(es)"
exit 0
