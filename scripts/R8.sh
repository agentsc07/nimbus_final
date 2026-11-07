#!/usr/bin/env bash
# R8 — Edge Node Takeover (FR-7, E5)
#
# This launcher intentionally performs a capability gate before running a
# failover trial.  Nimbus currently has durable SQLite recovery and in-process
# failover tests, but no safe multi-process primary/standby ownership protocol.
# Running two supervisors against the same state would therefore be a
# split-brain test, not evidence of a standby takeover.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/R8.sh --smoke
  ./scripts/R8.sh --full

--smoke checks the prerequisites for one real primary/standby takeover trial.
--full  checks the prerequisites for the planned ten deterministic trials.

The launcher creates results/final/R8/ evidence.  It will not substitute the
existing in-process failover test for a separate-process takeover experiment.
EOF
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

case "$1" in
  --smoke) planned_trials=1 ;;
  --full) planned_trials=10 ;;
  *) usage >&2; exit 2 ;;
esac

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
result_dir="$repo_root/results/final/R8"
raw_dir="$result_dir/raw"
mkdir -p "$raw_dir"

checked_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
runner="$repo_root/edge/run_supervisor.py"
store="$repo_root/edge/store/local_store.py"
takeover_test="$repo_root/edge/tests/test_failover_takeover.py"
e5="$repo_root/edge/benchmarks/e5_benchmark.py"

reasons=()

if [[ ! -f "$runner" || ! -f "$store" || ! -f "$takeover_test" || ! -f "$e5" ]]; then
  reasons+=("required edge supervisor, persistence, or failover sources are missing")
fi

# The runner has no role/node identity or controlled standby-activation
# interface.  Its recovery runs on startup, so two running processes could both
# attempt recovery from the same store.
if ! rg -q -- '--standby|--role|--node-id|leader' "$runner" 2>/dev/null; then
  reasons+=("edge/run_supervisor.py exposes no primary/standby role, node identity, or leader activation interface")
fi

# SQLite persistence records lease versions, but lacks a leader ownership claim
# or fencing token that can prevent a former primary from acting after takeover.
if ! rg -q 'fenc|leader|owner.*lease|lease.*owner|claim.*lease' "$store" 2>/dev/null; then
  reasons+=("edge/store/local_store.py has no lease-owner claim or fencing mechanism for concurrent supervisors")
fi

# The supplied evidence is deliberately not accepted: both implementations
# create/delete supervisors within one interpreter rather than terminating a
# primary OS process and observing a distinct standby process.
if ! rg -q 'subprocess|Popen|multiprocessing' "$takeover_test" 2>/dev/null; then
  reasons+=("test_failover_takeover.py is in-process and does not exercise separate supervisor PIDs")
fi
if ! rg -q 'subprocess|Popen|multiprocessing' "$e5" 2>/dev/null; then
  reasons+=("e5_benchmark.py is in-process and is not valid separate-process takeover evidence")
fi

# A process-local MockRobot cannot provide a shared command execution record
# with which to prove zero duplicate physical commands across two processes.
if ! rg -q 'shared.*robot|robot.*shared|execution.*log|command.*audit' "$runner" 2>/dev/null; then
  reasons+=("the supervisor runner has no shared robot command audit interface for cross-process duplicate verification")
fi

{
  printf 'R8 prerequisite check at %s\n' "$checked_utc"
  printf 'requested_mode=%s\n' "$1"
  printf 'planned_trials=%s\n' "$planned_trials"
  printf '\nBlocking findings:\n'
  for reason in "${reasons[@]}"; do
    printf '%s\n' "- $reason"
  done
  printf '\nNo primary or standby process was started.\n'
} > "$raw_dir/prerequisites.txt"

cat > "$result_dir/results.csv" <<'EOF'
run,task_id,primary_pid,standby_pid,failure_stage,takeover_time_s,duplicate_actions,lease_conflict,task_resumed,success,failure_reason
1,N/A,N/A,N/A,prerequisite_check,N/A,N/A,N/A,false,false,"BLOCKED: no multi-process leadership/fencing and no shared robot execution audit"
EOF

cat > "$result_dir/summary.csv" <<EOF
planned_trials,executed_trials,passed,blocked,takeover_time_s,duplicate_actions,lease_conflict,task_resumed,verdict
$planned_trials,0,0,1,N/A,N/A,N/A,false,BLOCKED
EOF

cat > "$result_dir/env.json" <<EOF
{
  "experiment": "R8",
  "mode": "$1",
  "planned_trials": $planned_trials,
  "checked_utc": "$checked_utc",
  "backend": "not started",
  "result": "BLOCKED",
  "reason": "Nimbus does not currently provide safe, observable multi-process primary/standby takeover."
}
EOF

cat > "$result_dir/README.md" <<EOF
# R8 — Edge Node Takeover

Status: **BLOCKED** (checked $checked_utc; requested mode: \`$1\`).

No trial was launched and no supervisor process was terminated. This is
intentional: a valid R8 trial requires a separately running standby that can
atomically assume ownership after the primary PID is killed. The current
supervisor runner has no primary/standby role, node identity, leader election,
lease ownership claim, or fencing token. Starting two supervisors against the
same SQLite state could allow both to recover and act concurrently.

The existing \`edge/tests/test_failover_takeover.py\` and
\`edge/benchmarks/e5_benchmark.py\` construct supervisors in one interpreter;
they do not terminate a primary OS process or demonstrate standby activation.
They are therefore not used as R8 evidence. The mock robot execution state is
also process-local, so it cannot prove that two processes issued zero duplicate
robot commands.

Consequently, takeover time, duplicate actions, lease conflicts, and task
resumption are all **not measured**. See \`raw/prerequisites.txt\` for the
specific capability findings.

To make R8 executable, Nimbus needs: (1) a durable, atomic leadership/lease
claim with fencing; (2) explicit standby activation and a separate node ID in
the supervisor runner; and (3) a shared, durable robot command execution audit
so duplicate commands can be detected across processes.
EOF

printf '[R8] BLOCKED: no safe, observable multi-process primary/standby takeover is available.\n'
printf '[R8] Findings: %s\n' "$raw_dir/prerequisites.txt"
printf '[R8] Wrote %s (no supervisor processes were started).\n' "$result_dir"
