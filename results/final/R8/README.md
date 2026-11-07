# R8 — Edge Node Takeover

Status: **BLOCKED** (checked 2026-11-07T17:41:43Z; requested mode: `--smoke`).

No trial was launched and no supervisor process was terminated. This is
intentional: a valid R8 trial requires a separately running standby that can
atomically assume ownership after the primary PID is killed. The current
supervisor runner has no primary/standby role, node identity, leader election,
lease ownership claim, or fencing token. Starting two supervisors against the
same SQLite state could allow both to recover and act concurrently.

The existing `edge/tests/test_failover_takeover.py` and
`edge/benchmarks/e5_benchmark.py` construct supervisors in one interpreter;
they do not terminate a primary OS process or demonstrate standby activation.
They are therefore not used as R8 evidence. The mock robot execution state is
also process-local, so it cannot prove that two processes issued zero duplicate
robot commands.

Consequently, takeover time, duplicate actions, lease conflicts, and task
resumption are all **not measured**. See `raw/prerequisites.txt` for the
specific capability findings.

To make R8 executable, Nimbus needs: (1) a durable, atomic leadership/lease
claim with fencing; (2) explicit standby activation and a separate node ID in
the supervisor runner; and (3) a shared, durable robot command execution audit
so duplicate commands can be detected across processes.
