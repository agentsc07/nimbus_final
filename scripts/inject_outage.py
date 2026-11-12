#!/usr/bin/env python3
"""scripts/inject_outage.py — Controlled model-outage and reconciliation check for Nimbus (PRD FR-18 / E5, FR-12).

Checks, each reported PASS, FAIL or NOT RUN (the exit code is 0 only when every check passed):
1. E5 / FR-18: makes the model unavailable via POST /llm/outage, submits a request during the outage and one after it,
   and requires a recorded fallback reason in the first decision and a model id in the second.
2. FR-12: sends POST /fleet/heartbeat from the cluster holding the lease of one of the two tasks this script created,
   first quoting the current lease version (expects reconcile action "ok"), then an older one (expects "replaced").
   Side effects: the cloud re-publishes that task's current lease, and the heartbeat counts as liveness for that
   cluster. NOT RUN when neither task got a lease (e.g. it needs clarification or is queued).
No network fault is injected, so nothing here measures E4 (network faults) or NFR-2 (recovery after a link outage);
the script does not inspect SQS.

Auth: requests carry `Authorization: Bearer <token>` from the environment when set — NIMBUS_ADMIN_TOKEN (or
NIMBUS_FAULT_TOKEN) for /llm/outage, NIMBUS_OPERATOR_TOKEN for the other routes, with NIMBUS_REQUESTER_TOKEN /
NIMBUS_EDGE_TOKEN and the master NIMBUS_AUTH_TOKEN as fallbacks.

Usage:
    python scripts/inject_outage.py                                   # NIMBUS_CLOUD_URL or http://127.0.0.1:8000
    python scripts/inject_outage.py --api https://<api-id>.execute-api.ap-south-1.amazonaws.com --seconds 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib import error as urlerr
from urllib import request as urlreq

DEFAULT_API = os.environ.get("NIMBUS_CLOUD_URL", "http://127.0.0.1:8000")
REGION = "ap-south-1"

# Environment variables tried, in order, for each kind of route (server.py accepts these tokens for these routes).
TOKEN_ENV = {
    "admin": ("NIMBUS_ADMIN_TOKEN", "NIMBUS_FAULT_TOKEN", "NIMBUS_AUTH_TOKEN"),
    "operator": ("NIMBUS_OPERATOR_TOKEN", "NIMBUS_ADMIN_TOKEN", "NIMBUS_AUTH_TOKEN"),
    "requester": ("NIMBUS_OPERATOR_TOKEN", "NIMBUS_REQUESTER_TOKEN", "NIMBUS_AUTH_TOKEN"),
    "edge": ("NIMBUS_OPERATOR_TOKEN", "NIMBUS_EDGE_TOKEN", "NIMBUS_AUTH_TOKEN"),
}


def _token(role: str) -> str | None:
    return next((os.environ[v] for v in TOKEN_ENV[role] if os.environ.get(v)), None)


def call_json(method: str, url: str, body: dict | None = None, timeout: float = 15.0, role: str = "operator") -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlreq.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    token = _token(role)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urlerr.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"raw": content}
        return e.code, parsed
    except Exception as ex:
        return -1, {"error": str(ex)}


def _cloud_llm(api: str, task_id: str | None) -> dict:
    """The `llm` block of the task's first cloud decision ({} when there is none)."""
    if not task_id:
        return {}
    _, tl = call_json("GET", f"{api}/tasks/{task_id}/timeline", role="requester")
    entry = next((e for e in tl.get("timeline", []) if e.get("who") == "cloud"), {})
    return entry.get("output", {}).get("llm", {}) or {}


def run_outage_test(api_base: str, outage_seconds: int = 60) -> dict:
    api = api_base.rstrip("/")
    results = {"E5 (FR-18)": "NOT RUN", "FR-12": "NOT RUN"}
    print("=== Nimbus controlled model-outage test ===")
    print(f"Target API: {api}")
    print(f"Outage window: {outage_seconds} seconds")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")

    # 1. Baseline
    _, cost_before = call_json("GET", f"{api}/cost")
    print("[1/4] Baseline snapshot:")
    print(f"  Counters before: llm_calls={cost_before.get('counters', {}).get('llm_calls')}\n")

    # 2. Model outage (E5 / FR-18)
    print(f"[2/4] Making the model unavailable for {outage_seconds}s via POST /llm/outage...")
    code, outage_res = call_json("POST", f"{api}/llm/outage", {"seconds": outage_seconds}, role="admin")
    print(f"  POST /llm/outage -> HTTP {code}: {outage_res}")
    if code != 201:
        results["E5 (FR-18)"] = "FAIL"
        print("  Outage could not be injected (set NIMBUS_ADMIN_TOKEN, or NIMBUS_DEMO_FAULTS=1 on a local server).")
        _print_summary(results, {"E5 (FR-18)": f"POST /llm/outage returned HTTP {code}"})
        return results

    outage_mid = f"outage-test-{uuid.uuid4().hex[:8]}"
    code, req_res = call_json("POST", f"{api}/requests", {"text": "Need an infusion pump at 2B-12, urgent.",
                                                          "message_id": outage_mid}, role="requester")
    outage_task_id = req_res.get("task_id")
    print(f"  POST /requests during outage -> HTTP {code}: task_id={outage_task_id}, notice={req_res.get('notice', '')!r}")
    llm_outage = _cloud_llm(api, outage_task_id)
    print(f"  Decision during outage: llm={llm_outage}")

    # 3. Recovery
    wait_time = outage_seconds + 5
    print(f"\n[3/4] Waiting {wait_time}s for the outage window to elapse...")
    time.sleep(wait_time)
    recovery_mid = f"rec-test-{uuid.uuid4().hex[:8]}"
    code, rec_res = call_json("POST", f"{api}/requests", {"text": "Need a wheelchair at 3C-01, routine.",
                                                          "message_id": recovery_mid}, role="requester")
    recovery_task_id = rec_res.get("task_id")
    print(f"  POST /requests after recovery -> HTTP {code}: task_id={recovery_task_id}")
    llm_rec = _cloud_llm(api, recovery_task_id)
    print(f"  Decision after recovery: llm={llm_rec}\n")
    e5_ok = bool(llm_outage.get("fallback_reason")) and llm_rec.get("model") is not None and not llm_rec.get("fallback_reason")
    results["E5 (FR-18)"] = "PASS" if e5_ok else "FAIL"
    evidence = {"E5 (FR-18)": f"fallback during outage: {llm_outage.get('fallback_reason')!r}; "
                              f"model after recovery: {llm_rec.get('model')!r}"}

    # 4. Reconciliation (FR-12) on one of this script's own tasks
    print("[4/4] Edge reconciliation (FR-12) on a lease this script's requests produced...")
    lease, statuses = {}, []
    for tid in (outage_task_id, recovery_task_id):
        _, task = call_json("GET", f"{api}/tasks/{tid}", role="requester") if tid else (0, {})
        statuses.append(f"{tid}: {task.get('status')!r}")
        lease = task.get("lease") or {}
        if lease.get("lease_id") and isinstance(lease.get("version"), int) and lease.get("cluster_id"):
            break
        lease = {}
    if not lease:
        evidence["FR-12"] = f"no live lease to reconcile ({'; '.join(statuses)})"
    else:
        lid, ver, cluster = lease["lease_id"], lease["version"], lease["cluster_id"]
        replies = []
        for quoted in (ver, ver - 1):
            hb_code, hb_res = call_json("POST", f"{api}/fleet/heartbeat",
                                        {"cluster_id": cluster, "leases": [{"lease_id": lid, "version": quoted}]}, role="edge")
            action = (hb_res.get("reconcile") or [{}])[0].get("action")
            print(f"  heartbeat {cluster} quoting {lid} v{quoted} -> HTTP {hb_code}: reconcile={hb_res.get('reconcile')}")
            replies.append((hb_code, action))
        ok = replies == [(201, "ok"), (201, "replaced")]
        results["FR-12"] = "PASS" if ok else "FAIL"
        evidence["FR-12"] = f"current version -> {replies[0][1]!r} (want 'ok'); older version -> {replies[1][1]!r} (want 'replaced')"

    _, cost_after = call_json("GET", f"{api}/cost")
    print(f"  Counters after: llm_calls={cost_after.get('counters', {}).get('llm_calls')}")
    _print_summary(results, evidence)
    return results


def _print_summary(results: dict, evidence: dict) -> None:
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"{'Check':<12} {'Result':<8} Evidence")
    print("-" * 60)
    for check, verdict in results.items():
        print(f"{check:<12} {verdict:<8} {evidence.get(check, '')}")
    print("Not measured here: E4 and NFR-2 (no network fault is injected).")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run the controlled model-outage and reconciliation check")
    parser.add_argument("--api", default=DEFAULT_API, help="Cloud base URL (local server or API Gateway)")
    parser.add_argument("--seconds", type=int, default=30, help="Outage duration in seconds")
    args = parser.parse_args()
    results = run_outage_test(args.api, args.seconds)
    sys.exit(0 if all(v == "PASS" for v in results.values()) else 1)


if __name__ == "__main__":
    main()
