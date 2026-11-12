"""N10: requester app and operator console (FR-21, FR-22), measured at the cloud control API.

    python results/final/N10/run_n10.py              # no target: starts an in-process local server on 127.0.0.1
    NIMBUS_CLOUD_URL=http://host:port python results/final/N10/run_n10.py   # an existing cloud; exits 2 if GET /health fails
    python results/final/N10/run_n10.py --no-video   # skip the optional Playwright recording

What is measured: the round trip of the operator's POST /tasks/{id}/control (cancel and pause) to the cloud, the task
status the cloud reports afterwards, and whether the cloud issued a new (stop) lease version. What is NOT measured:
delivery of that stop lease to an edge or robot, an edge acknowledgement, or robot deceleration; no edge runs here.
SC-1 is driven through the requester API; its OUTPUT_READY is posted by this script (simulated edge completion).
Against a token-protected cloud the script sends `Authorization: Bearer` from NIMBUS_REQUESTER_TOKEN /
NIMBUS_OPERATOR_TOKEN / NIMBUS_EDGE_TOKEN (or NIMBUS_AUTH_TOKEN).
"""

import os
import sys
import time
import json
import shutil
import random
import argparse
import tempfile
import urllib.request
import urllib.error
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.getcwd())
from scripts.p4_shared import (
    COLOR_C1, COLOR_C2, COLOR_C3, COLOR_PASS_BAR,
    setup_matplotlib_style, save_plots, write_env_json, write_readme
)

API_BASE = None
PASS_BAR_S = 5.0
EDGE_PATHS = ("/checkins", "/escalations", "/fleet/heartbeat", "/relay/decide", "/outbox", "/results/upload-url")
ROLE_TOKENS = {
    "requester": ("NIMBUS_REQUESTER_TOKEN", "NIMBUS_OPERATOR_TOKEN", "NIMBUS_AUTH_TOKEN"),
    "operator": ("NIMBUS_OPERATOR_TOKEN", "NIMBUS_ADMIN_TOKEN", "NIMBUS_AUTH_TOKEN"),
    "edge": ("NIMBUS_EDGE_TOKEN", "NIMBUS_OPERATOR_TOKEN", "NIMBUS_AUTH_TOKEN"),
}


def _role(method, path):
    segments = path.split("/")
    if path in EDGE_PATHS:
        return "edge"
    if path == "/requests" or (path.startswith("/requests/") and path.endswith("/answer")):
        return "requester"
    if method == "GET" and segments[1:2] == ["tasks"] and len(segments) in (2, 3):
        return "requester"
    return "operator"


def api_call(method, path, body=None, timeout=10):
    """(HTTP status, JSON body); HTTP errors are returned, not raised, so they are recorded."""
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    token = next((os.environ[k] for k in ROLE_TOKENS[_role(method, path)] if os.environ.get(k)), None)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return exc.code, {"error": str(exc)}


def select_target():
    """NIMBUS_CLOUD_URL set: probe GET /health and exit non-zero if unreachable (no silent fallback).
    Not set: start an in-process local server on 127.0.0.1 (auth disabled; local, non-production)."""
    url = (os.environ.get("NIMBUS_CLOUD_URL") or "").strip().rstrip("/")
    if url:
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{url}/health"), timeout=5.0) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
        except Exception as exc:
            print(f"N10: NIMBUS_CLOUD_URL={url} is not reachable (GET /health: {exc}). "
                  "Not falling back to a local server; unset NIMBUS_CLOUD_URL to run against one.", file=sys.stderr)
            sys.exit(2)
        return url, None, f"NIMBUS_CLOUD_URL {url}", None
    import threading
    from pathlib import Path
    import server
    os.environ["NIMBUS_AUTH_DISABLED"] = "1"
    tmp_dir = Path(tempfile.mkdtemp(prefix="nimbus-n10-"))
    httpd = server.make_server("127.0.0.1", 0, tmp_dir)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)
    model = "rule-based stand-in" if os.environ.get("NIMBUS_LLM", "fake") != "bedrock" else "bedrock (NIMBUS_LLM=bedrock)"
    return f"http://127.0.0.1:{httpd.server_address[1]}", httpd, "local in-process server.py on 127.0.0.1", model


def lease_version(task):
    return (task.get("lease") or {}).get("version")


def run_sc1():
    """SC-1 through the requester API: request -> clarification answer -> lease -> OUTPUT_READY -> completed.
    The OUTPUT_READY is posted by this script with the task's lease version: a simulated edge completion."""
    rec = {"request_text": "Need an infusion pump at 2B-12, urgent", "edge_completion": "simulated (posted by this script)"}
    code, resp = api_call("POST", "/requests", {"text": rec["request_text"], "message_id": f"n10-sc1-{int(time.time() * 1000)}"})
    rec["request_status_code"] = code
    tid = resp.get("task_id")
    rec["task_id"] = tid
    if not tid:
        rec.update(final_status=None, completed=False)
        return rec
    _, task = api_call("GET", f"/tasks/{tid}")
    rec["initial_status"] = task.get("status")
    if task.get("status") == "needs_clarification":
        code, _ = api_call("POST", f"/requests/{tid}/answer", {"text": "paediatric", "message_id": f"n10-sc1-ans-{tid}"})
        rec["answer_status_code"] = code
        _, task = api_call("GET", f"/tasks/{tid}")
    rec["status_before_completion"] = task.get("status")
    rec["lease_version"] = lease_version(task)
    code, _ = api_call("POST", "/escalations", {
        "task_id": tid, "type": "OUTPUT_READY", "lease_version": lease_version(task) or 1,
        "payload": {"result_ref": f"local://outputs/{tid}/delivery-confirmed"},
        "message_id": f"n10-sc1-esc-{tid}-{int(time.time() * 1000)}"})
    rec["output_ready_status_code"] = code
    _, task = api_call("GET", f"/tasks/{tid}")
    rec["final_status"] = task.get("status")
    rec["completed"] = task.get("status") == "completed"
    return rec


def record_videos(out_dir, video_dir):
    """Optional UI recordings. Skipped with a notice when Playwright or its Chromium is missing; existing videos are
    never deleted. Recordings go to a temp dir first, then are copied over the files of the same name."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return {"recorded": False, "reason": f"playwright not importable ({exc})"}
    saved = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for name, flow in (("sc1_completed_flow", "sc1"), ("cancel_override_flow", "cancel")):
                tmp = tempfile.mkdtemp(prefix="nimbus-n10-video-")
                context = browser.new_context(record_video_dir=tmp, viewport={"width": 1280, "height": 800})
                page = context.new_page()
                page.goto(f"{API_BASE}/operator")
                page.wait_for_timeout(2000)
                if flow == "sc1":
                    run_sc1()                       # SC-1 with simulated edge completion, shown on the console
                else:
                    _, resp = api_call("POST", "/requests", {"text": "Please bring a wheelchair to ward 2C",
                                                             "message_id": f"n10-vid-c-{int(time.time() * 1000)}"})
                    page.wait_for_timeout(2000)
                    if resp.get("task_id"):
                        api_call("POST", f"/tasks/{resp['task_id']}/control",
                                 {"action": "cancel", "message_id": f"n10-vid-cancel-{int(time.time() * 1000)}"})
                page.wait_for_timeout(3500)
                vid = page.video.path()
                page.close()
                context.close()
                if os.path.exists(vid):
                    for dest in (os.path.join(out_dir, f"{name}.webm"), os.path.join(video_dir, f"{name}.webm")):
                        shutil.copy2(vid, dest)
                    saved.append(f"{name}.webm")
                shutil.rmtree(tmp, ignore_errors=True)
            browser.close()
    except Exception as exc:
        return {"recorded": bool(saved), "saved": saved, "reason": f"Playwright/Chromium not available or failed ({str(exc).splitlines()[0]})"}
    return {"recorded": True, "saved": saved}


def run_n10():
    global API_BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-video", action="store_true", help="skip the optional Playwright recording")
    args = ap.parse_args()

    out_dir = os.path.join("results", "final", "N10")
    plot_dir = os.path.join(out_dir, "plots")
    video_dir = os.path.join(out_dir, "videos")
    os.makedirs(plot_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)
    setup_matplotlib_style()

    API_BASE, httpd, target_desc, model = select_target()
    print(f"=== N10: target {target_desc} ===")

    # Stock so the requests below can be leased
    for cid in ("west-wing", "east-wing"):
        code, resp = api_call("POST", "/inventory/stock", {"cluster_id": cid, "stock": {"blanket": 50, "wheelchair": 20, "infusion_pump": 20, "infusion_pump_paediatric": 20, "iv_pole": 20}})
        if code >= 300:
            print(f"Stock reset notice for {cid}: HTTP {code} {resp}")

    # 1. 20 cancels and 20 pauses (the console's urgent override) across 10 seeds, timed at the control API
    print("[1/3] 20 cancels and 20 pauses across 10 seeds (cloud control-API round trip)...")
    records = []
    for seed in range(1, 11):
        rng = random.Random(seed)
        for kind, action, text, want in (("cancel", "cancel", "Need a blanket at ward 2C", "cancelled"),
                                          ("urgent_override", "pause", "Need an iv pole at ward 2C", "paused")):
            for it in range(2):
                op_idx = (seed - 1) * 2 + it + 1
                _, task_resp = api_call("POST", "/requests", {"text": text, "message_id": f"n10-s{seed}-{action}{it}-{int(time.time() * 1000)}"})
                tid = task_resp.get("task_id")
                _, before = api_call("GET", f"/tasks/{tid}") if tid else (None, {})
                time.sleep(rng.uniform(0.05, 0.15))
                t0 = time.perf_counter()
                code, ctrl = api_call("POST", f"/tasks/{tid}/control", {"action": action, "message_id": f"n10-ctrl-{action}{op_idx}-{int(time.time() * 1000)}"})
                lat = time.perf_counter() - t0
                _, after = api_call("GET", f"/tasks/{tid}") if tid else (None, {})
                v0, v1 = lease_version(before), lease_version(after)
                accepted = 200 <= code < 300 and after.get("status") == want
                cleanup = None
                if action == "pause" and tid:   # untimed: cancel the paused task so its robot is free for the next request
                    cleanup, _ = api_call("POST", f"/tasks/{tid}/control", {"action": "cancel", "message_id": f"n10-cleanup-{op_idx}-{int(time.time() * 1000)}"})
                records.append({
                    "seed": seed, "operation_idx": op_idx, "operation": kind, "action": action, "task_id": tid,
                    "status_before": before.get("status"), "lease_version_before": v0,
                    "control_http_status": code, "control_rtt_seconds": round(lat, 4),
                    "status_after": after.get("status"), "lease_version_after": v1,
                    "stop_lease_issued_by_cloud": bool(v0 is not None and v1 is not None and v1 > v0),
                    "accepted": accepted, "pass_5s": accepted and lat <= PASS_BAR_S, "cleanup_cancel_http_status": cleanup,
                    "robot_receipt": "not measured", "source": "measured",
                })

    df = pd.DataFrame(records)
    df.to_csv(os.path.join(out_dir, "cancel.csv"), index=False)

    summary_rows = []
    for seed, g in df.groupby("seed"):
        c = g[g["operation"] == "cancel"]["control_rtt_seconds"]
        o = g[g["operation"] == "urgent_override"]["control_rtt_seconds"]
        summary_rows.append({
            "seed": seed, "n_cancels": len(c), "n_overrides": len(o),
            "p50_cancel_rtt_s": round(float(np.percentile(c, 50)), 4), "p95_cancel_rtt_s": round(float(np.percentile(c, 95)), 4),
            "p50_override_rtt_s": round(float(np.percentile(o, 50)), 4), "p95_override_rtt_s": round(float(np.percentile(o, 95)), 4),
            "max_rtt_s": round(float(g["control_rtt_seconds"].max()), 4),
            "accepted": int(g["accepted"].sum()), "stop_leases_issued": int(g["stop_lease_issued_by_cloud"].sum()),
            "pass_5s": bool(g["pass_5s"].all()), "source": "measured",
        })
    pd.DataFrame(summary_rows).to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    # 2. SC-1 through the requester API (simulated edge completion)
    print("[2/3] SC-1 via the requester API (OUTPUT_READY posted by this script)...")
    sc1 = run_sc1()
    with open(os.path.join(out_dir, "sc1.json"), "w", encoding="utf-8") as f:
        json.dump(sc1, f, indent=2)
        f.write("\n")

    # Plot: control-API round-trip CDF
    all_c = df[df["operation"] == "cancel"]["control_rtt_seconds"].values
    all_o = df[df["operation"] == "urgent_override"]["control_rtt_seconds"].values
    fig, ax = plt.subplots(figsize=(7, 5))
    for vals, col, lab in ((all_c, COLOR_C1, "Cancel"), (all_o, COLOR_C2, "Pause (urgent override)")):
        x = np.sort(vals)
        ax.step(x, np.arange(1, len(x) + 1) / len(x), where="post", color=col, linewidth=2.2, label=f"{lab} (p95={np.percentile(vals, 95):.3f} s)")
    ax.axvline(PASS_BAR_S, color=COLOR_PASS_BAR, linestyle="--", linewidth=2.0, label="PRD Pass Bar (5.0 s)")
    ax.set_xscale("log")
    ax.set_xlabel("Cloud control-API round trip, POST /tasks/{id}/control (seconds, log scale)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title(f"N10: Operator control round trip, {target_desc} (robot receipt not measured)")
    ax.set_ylim(0, 1.05)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="lower right", frameon=True)
    save_plots(fig, plot_dir, "cancel_latency_cdf")

    # 3. Optional videos
    if args.no_video:
        video = {"recorded": False, "reason": "--no-video"}
    else:
        print("[3/3] Optional Playwright recording...")
        video = record_videos(out_dir, video_dir)
    if not video.get("recorded"):
        print(f"  Video step skipped: {video.get('reason')}. Existing videos are left untouched.")

    if httpd:
        httpd.shutdown()

    p95_c, p95_o = float(np.percentile(all_c, 95)), float(np.percentile(all_o, 95))
    max_rtt = float(df["control_rtt_seconds"].max())
    n_ops, n_acc = len(df), int(df["accepted"].sum())
    n_ok = int(df["pass_5s"].sum())
    n_stop = int(df["stop_lease_issued_by_cloud"].sum())
    n_leased = int(df["lease_version_before"].notna().sum())
    cloud_ok = n_ok == n_ops
    sc1_ok = bool(sc1.get("completed"))
    verdict = "PASS (cloud side only; edge/robot receipt not measured)" if (cloud_ok and sc1_ok) else "FAIL"

    env = write_env_json(out_dir, experiment="N10", title="Requester app and operator console", prd="FR-21, FR-22",
                         source="measured", target=target_desc, model=model, seeds=list(range(1, 11)),
                         video=video)
    measured = (f"{target_desc}: cloud control-API round trip (POST /tasks/{{id}}/control) cancel p95 {p95_c:.3f} s, "
                f"pause p95 {p95_o:.3f} s, max {max_rtt:.3f} s; {n_ok}/{n_ops} acknowledged within {PASS_BAR_S:.0f} s with the "
                f"expected status; {n_stop}/{n_leased} leased tasks got a new stop-lease version from the cloud"
                + (f" ({n_ops - n_leased} were still queued, nothing to stop)" if n_leased < n_ops else "") + "; "
                f"stop-lease delivery to edge/robots not measured; SC-1 with simulated edge completion: final status "
                f"{sc1.get('final_status')}")
    notes = [
        "Measured: the HTTP round trip of the operator's control call and the status/lease version the cloud reports "
        "afterwards. Not measured: publication of the stop lease to an edge, an edge acknowledgement, or a robot stopping; "
        "no edge or robot runs in this experiment. The FR-22 'reaches robots within 5 s' part is therefore untested here.",
        f"Target: {target_desc}. With no NIMBUS_CLOUD_URL the runner starts server.py in-process on 127.0.0.1 with "
        "NIMBUS_AUTH_DISABLED=1 (local only); with NIMBUS_CLOUD_URL set it exits with status 2 if GET /health fails, "
        "instead of silently measuring a local server. Nothing here ran against the deployed AWS cloud.",
        "Each paused task is then cancelled (untimed, cleanup_cancel_http_status in cancel.csv) so its robot is free and "
        "the next request can be leased rather than queued; Measured counts how many timed calls hit a leased task.",
        "SC-1 is driven through the requester API; the OUTPUT_READY that completes it is posted by this script with the "
        "task's lease version (simulated edge completion). sc1.json records each step.",
        "Verdict rule: PASS iff every control call is acknowledged with the expected status within 5 s and SC-1 reaches "
        "'completed'; the PASS covers the cloud side only.",
        ("Videos re-recorded by this run (local target, SC-1 OUTPUT_READY posted by the script): "
         + ", ".join(video.get("saved", [])) + "." if video.get("recorded") else
         f"Video step skipped ({video.get('reason')}). sc1_completed_flow.webm and cancel_override_flow.webm predate this "
         "change and were not re-recorded (earlier version of this runner; its SC-1 OUTPUT_READY was also posted by the script)."),
        "demo_completed_flow.webm and demo_cancel_flow.webm come from scripts/record_n10_videos.py, not from this runner, "
        "and predate this change. The recording loads the operator page, which fetches fonts and three.js from public CDNs.",
    ]
    write_readme(out_dir, exp_id="N10", title="Requester app and operator console",
                 claim="Operator cancel and pause calls are acknowledged by the cloud control API well within 5 s, and SC-1 reaches 'completed' through the requester API when the edge completion is simulated.",
                 pass_bar="SC-1 completes from app; cancel or override reaches robots within 5 s (FR-21, FR-22).",
                 measured=measured, verdict=verdict, env=env, notes=notes)
    print(f"N10: {n_ok}/{n_ops} control calls within 5 s, SC-1 {sc1.get('final_status')} -> {verdict}")


if __name__ == "__main__":
    run_n10()
