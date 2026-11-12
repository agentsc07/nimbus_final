"""N4: duplicate and replayed messages at the cloud's request ingress (FR-8), on a live local server.

    python results/final/N4/run_n4.py

Per seed (10 seeds), against server.py started in-process on 127.0.0.1 (auth disabled, stand-in model):
  - duplicate (150): 50 requests, each sent 3 times with the same message_id and payload;
  - replayed_id (100): 50 requests, each re-sent once with the same message_id and an altered text;
  - repeat_cancel_on_cancelled_task (150): fresh-id cancels of a task already cancelled (the server should answer 409);
  - fresh_unique_request (100): unique requests, the control group (each should be accepted once).
The last two are NOT stale-lease-version or re-ordering injections (no edge or lease version is involved); they are
named for what is sent. Every summary number is computed from the per-message records and a final GET /tasks.
"""

import os
import json
import uuid
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.getcwd())
from scripts.p4_shared import (
    COLOR_C1, COLOR_C2, COLOR_C3, COLOR_PASS_BAR,
    setup_matplotlib_style, save_plots, write_env_json, write_readme
)

CATEGORIES = ["duplicate", "replayed_id", "repeat_cancel_on_cancelled_task", "fresh_unique_request"]
CATEGORY_LABELS = {"duplicate": "Duplicate\n(same id, same text)", "replayed_id": "Replayed id\n(same id, new text)",
                   "repeat_cancel_on_cancelled_task": "Repeat cancel on\ncancelled task", "fresh_unique_request": "Fresh unique\nrequest (control)"}

def run_n4():
    out_dir = os.path.join("results", "final", "N4")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    # 10 seeds; 500 messages per seed (see the module docstring for what each category sends). The seed only
    # changes message ids and texts: the server's handling does not depend on randomness.
    seeds = list(range(1, 11))
    injection_records = []
    summary_rows = []

    import tempfile
    import threading
    import urllib.request
    from urllib.error import HTTPError
    from pathlib import Path
    import server

    # Run live local HTTP server instance to exercise real server ingress deduplication
    os.environ["NIMBUS_AUTH_DISABLED"] = "1"
    tmp_dir = Path(tempfile.mkdtemp(prefix="nimbus-n4-"))
    httpd = server.make_server("127.0.0.1", 0, tmp_dir)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    server_url = f"http://127.0.0.1:{httpd.server_address[1]}"

    def _http_get(path: str) -> tuple[int, dict]:
        with urllib.request.urlopen(urllib.request.Request(f"{server_url}{path}"), timeout=10.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _reason(status_code: int, resp: dict) -> str:
        if resp.get("duplicate") is True:
            return "duplicate message_id" + (" (in flight)" if status_code == 409 else "")
        return str(resp.get("error") or "")

    def _record(seed, task_type, category, msg_id, first, status_code, resp, expect):
        """expect: 'accept' (first delivery / control), 'drop' (repeat of an id), 'reject' (409 on a finished task)."""
        executed_again = 1 if expect == "drop" and resp.get("duplicate") is not True and 200 <= status_code < 300 else 0
        if expect == "accept":
            ok = 200 <= status_code < 300 and resp.get("duplicate") is not True
            action = "accepted" if ok else f"unexpected_http_{status_code}"
        elif expect == "drop":
            ok = resp.get("duplicate") is True
            action = "dropped_duplicate" if ok else ("EXECUTED_AGAIN" if executed_again else f"unexpected_http_{status_code}")
        else:
            ok = status_code == 409
            action = "rejected_409" if ok else f"unexpected_http_{status_code}"
        injection_records.append({
            "seed": seed, "task": task_type, "injection_type": category, "message_id": msg_id,
            "first_delivery": first, "expected": expect, "status_code": status_code, "action_taken": action,
            "reason_returned": _reason(status_code, resp), "as_expected": ok,
            "duplicate_executed": executed_again, "source": "simulated",
        })

    def _http_post(path: str, body: dict) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{server_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                err_body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                err_body = {"error": str(exc)}
            return exc.code, err_body

    try:
        for seed in seeds:
            task_type = "T1" if seed % 2 == 1 else "T4"   # label only: which request family the texts imitate

            # 1. Duplicates: 50 unique message ids, each delivered 3 times with the same payload
            for i in range(150):
                msg_id = f"mid-dup-s{seed}-{i//3}"
                status_code, resp = _http_post("/requests", {
                    "text": f"Delivery of medical supplies for seed {seed} item {i//3}",
                    "message_id": msg_id,
                })
                _record(seed, task_type, "duplicate", msg_id, i % 3 == 0, status_code, resp,
                        "accept" if i % 3 == 0 else "drop")

            # 2. Replayed ids: 50 unique message ids, each re-sent once with an altered text
            for i in range(100):
                msg_id = f"mid-replay-s{seed}-{i//2}"
                is_first = (i % 2 == 0)
                text = f"Initial request {i//2}" if is_first else f"Altered malicious request {i//2}"
                status_code, resp = _http_post("/requests", {"text": text, "message_id": msg_id})
                _record(seed, task_type, "replayed_id", msg_id, is_first, status_code, resp,
                        "accept" if is_first else "drop")

            # 3. Repeated cancels (fresh message ids) of a task that is already cancelled: expect 409 each time
            status_code, t_resp = _http_post("/requests", {
                "text": f"Task for repeat-cancel test seed {seed}",
                "message_id": f"mid-cancelbase-{seed}",
            })
            base_tid = t_resp.get("task_id")
            first_cancel, _ = _http_post(f"/tasks/{base_tid}/control", {"action": "cancel", "message_id": f"ctrl-cancel-{seed}"})
            for i in range(150):
                msg_id = f"mid-recancel-s{seed}-{i}"
                status_code, resp = _http_post(f"/tasks/{base_tid}/control", {"action": "cancel", "message_id": msg_id})
                _record(seed, task_type, "repeat_cancel_on_cancelled_task", msg_id, False, status_code, resp, "reject")

            # 4. Fresh unique requests (control group): each should be accepted exactly once
            for i in range(100):
                msg_id = f"mid-fresh-s{seed}-{i}"
                status_code, resp = _http_post("/requests", {"text": f"Fresh request {i} for seed {seed}", "message_id": msg_id})
                _record(seed, task_type, "fresh_unique_request", msg_id, True, status_code, resp, "accept")

        # State check: how many tasks the server actually created for each message family.
        _, all_tasks = _http_get("/tasks")
        texts = [t.get("request_text", "") for t in all_tasks.get("tasks", [])]
        state_check = {
            "tasks_total": len(texts),
            "tasks_from_altered_replays": sum(1 for t in texts if t.startswith("Altered malicious request")),
            "max_tasks_per_duplicated_message": max(
                (sum(1 for t in texts if t == f"Delivery of medical supplies for seed {sd} item {k}") for sd in seeds for k in range(50)),
                default=0),
            "duplicated_messages_with_no_task": sum(
                1 for sd in seeds for k in range(50) if f"Delivery of medical supplies for seed {sd} item {k}" not in texts),
        }
    finally:
        httpd.shutdown()
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    df_rec = pd.DataFrame(injection_records)
    for seed in seeds:
        g = df_rec[df_rec["seed"] == seed]
        repeats = g[g["expected"] == "drop"]
        summary_rows.append({
            "seed": seed,
            "task": g["task"].iloc[0],
            "total_injected": len(g),
            "duplicate_repeats_sent": int((repeats["injection_type"] == "duplicate").sum()),
            "duplicates_dropped": int(((repeats["injection_type"] == "duplicate") & repeats["as_expected"]).sum()),
            "replay_repeats_sent": int((repeats["injection_type"] == "replayed_id").sum()),
            "replayed_id_dropped": int(((repeats["injection_type"] == "replayed_id") & repeats["as_expected"]).sum()),
            "repeat_cancels_sent": int((g["injection_type"] == "repeat_cancel_on_cancelled_task").sum()),
            "repeat_cancels_rejected_409": int(((g["injection_type"] == "repeat_cancel_on_cancelled_task") & g["as_expected"]).sum()),
            "fresh_requests_sent": int((g["injection_type"] == "fresh_unique_request").sum()),
            "fresh_requests_accepted": int(((g["injection_type"] == "fresh_unique_request") & g["as_expected"]).sum()),
            "duplicate_steps_executed": int(g["duplicate_executed"].sum()),
            "drops_with_reason": int(((g["expected"] != "accept") & g["as_expected"] & (g["reason_returned"] != "")).sum()),
            "dedup_pass_rate_pct": round(100.0 * repeats["as_expected"].mean(), 2) if len(repeats) else None,
            "source": "simulated",
        })

    # Save e6_injection.csv
    df_inj = df_rec
    e6_path = os.path.join(out_dir, "e6_injection.csv")
    df_inj.to_csv(e6_path, index=False)

    # Save summary.csv
    df_sum = pd.DataFrame(summary_rows)
    sum_path = os.path.join(out_dir, "summary.csv")
    df_sum.to_csv(sum_path, index=False)

    with open(os.path.join(out_dir, "state_check.json"), "w", encoding="utf-8") as f:
        json.dump(state_check, f, indent=2)
        f.write("\n")

    # --- PLOTS ---
    # Plot 1: outcome counts per category, computed from the records
    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    sent = [int((df_inj["injection_type"] == c).sum()) for c in CATEGORIES]
    first_ok = [int(((df_inj["injection_type"] == c) & (df_inj["expected"] == "accept") & df_inj["as_expected"]).sum()) for c in CATEGORIES]
    dropped = [int(((df_inj["injection_type"] == c) & (df_inj["expected"] != "accept") & df_inj["as_expected"]).sum()) for c in CATEGORIES]
    wrong = [int(((df_inj["injection_type"] == c) & ~df_inj["as_expected"]).sum()) for c in CATEGORIES]
    x = np.arange(len(CATEGORIES))
    w = 0.2
    groups = [(sent, "Sent", COLOR_C3), (first_ok, "Accepted (first delivery / control)", COLOR_C1),
              (dropped, "Dropped (duplicate) or refused (409)", COLOR_C2), (wrong, "Not as expected", COLOR_PASS_BAR)]
    for k, (vals, lab, col) in enumerate(groups):
        bars = ax.bar(x + (k - 1.5) * w, vals, width=w, label=lab, color=col, edgecolor="black")
        for rect in bars:
            if rect.get_height() > 0:
                ax.text(rect.get_x() + rect.get_width() / 2., rect.get_height() + 10, f"{int(rect.get_height())}", ha="center", va="bottom", fontsize=7)
    ax.set_title(f"N4: Ingress outcomes over {len(df_inj)} messages in {len(seeds)} seeds (live local server)")
    ax.set_xticks(x)
    ax.set_xticklabels([CATEGORY_LABELS[c] for c in CATEGORIES], fontsize=8)
    ax.set_ylabel("Messages")
    ax.set_ylim(0, max(sent) * 1.4)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y")
    save_plots(fig, plot_dir, "injection_outcomes")

    # Plot 2: the real message sequence of seed 1, in send order, coloured by outcome
    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    s1 = df_inj[df_inj["seed"] == 1].reset_index(drop=True)
    lane = {c: i for i, c in enumerate(CATEGORIES)}
    for outcome, col, marker in (("accepted", COLOR_C1, "o"), ("dropped_duplicate", COLOR_C2, "x"), ("rejected_409", COLOR_PASS_BAR, "s")):
        sub = s1[s1["action_taken"] == outcome]
        ax.scatter(sub.index, sub["injection_type"].map(lane), color=col, marker=marker, s=14, label=outcome)
    bad = s1[~s1["as_expected"]]
    if len(bad):
        ax.scatter(bad.index, bad["injection_type"].map(lane), color="black", marker="*", s=60, label="not as expected")
    ax.set_yticks(list(lane.values()))
    ax.set_yticklabels([CATEGORY_LABELS[c].replace("\n", " ") for c in CATEGORIES], fontsize=8)
    ax.set_xlabel("Message send order within seed 1")
    ax.set_title("N4: Seed 1 message sequence and server outcome")
    ax.legend(loc="upper left", fontsize=8, ncol=4)
    ax.set_ylim(-0.6, len(CATEGORIES) - 0.2)
    ax.grid(True)
    save_plots(fig, plot_dir, "timeline_dedup")

    # Write env.json
    env = write_env_json(out_dir, experiment="N4", title="Duplicate and replayed messages at the cloud ingress", prd="FR-8",
                         source="simulated", target="local in-process server.py on 127.0.0.1, auth disabled",
                         model="rule-based stand-in", seeds=seeds)

    tot = df_sum[[c for c in df_sum.columns if c not in ("seed", "task", "source", "dedup_pass_rate_pct")]].sum()
    repeats_sent = int(tot["duplicate_repeats_sent"] + tot["replay_repeats_sent"])
    repeats_dropped = int(tot["duplicates_dropped"] + tot["replayed_id_dropped"])
    drops_total = repeats_dropped + int(tot["repeat_cancels_rejected_409"])
    executed_twice = int(tot["duplicate_steps_executed"])
    unexpected = int((~df_inj["as_expected"]).sum())
    state_ok = state_check["tasks_from_altered_replays"] == 0 and state_check["max_tasks_per_duplicated_message"] <= 1
    verdict_pass = (executed_twice == 0 and repeats_dropped == repeats_sent and unexpected == 0 and state_ok
                    and int(tot["drops_with_reason"]) == drops_total)
    measured = (f"{executed_twice} steps executed twice over {int(tot['total_injected'])} messages in {len(seeds)} seeds: "
                f"{repeats_dropped}/{repeats_sent} repeated message ids dropped as duplicates "
                f"({int(tot['duplicates_dropped'])} duplicates, {int(tot['replayed_id_dropped'])} replays with altered text); "
                f"{int(tot['repeat_cancels_rejected_409'])}/{int(tot['repeat_cancels_sent'])} repeat cancels of a cancelled task refused with 409; "
                f"{int(tot['fresh_requests_accepted'])}/{int(tot['fresh_requests_sent'])} fresh requests accepted; "
                f"server state: {state_check['tasks_from_altered_replays']} tasks from altered replays, at most "
                f"{state_check['max_tasks_per_duplicated_message']} task per duplicated message")
    notes = [
        "Real system: every message goes over HTTP to server.py's ingress (in-process, 127.0.0.1, rule-based stand-in model). "
        "The source stays `simulated` because the messages are synthetic and no edge, robot or lease-version traffic is involved.",
        "Renamed categories: what earlier versions called 'stale lease version' is a fresh-id cancel of an already-cancelled "
        "task (409), and 'shuffled order' is a set of fresh unique requests (the control group). No true stale-lease-version "
        "or re-ordering injection at the edge or check-in path is run here; R6 covers stale versions at the edge.",
        "Drop reasons: each drop is answered with a reason (duplicate flag or 409 error text) and recorded per message in "
        "e6_injection.csv by this harness. The server does not write a persistent drop-log row, so 'every drop logged' "
        "is met by the harness's record of the server's answer, not by a server-side log.",
        "Verdict rule: PASS iff no repeated message id is executed again, every repeat is dropped, every message gets the "
        "expected answer, every drop carries a reason, and GET /tasks shows no task from an altered replay and at most one "
        "task per duplicated message (state_check.json).",
    ]
    write_readme(out_dir, exp_id="N4", title="Duplicate and replayed messages at the cloud ingress",
                 claim="Repeated message ids at the cloud's request ingress are acknowledged but never executed twice, and controls on a finished task are refused.",
                 pass_bar="Zero steps executed twice (FR-8); every drop logged with reason.",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N4: {executed_twice} executed twice, {repeats_dropped}/{repeats_sent} repeats dropped, {unexpected} unexpected -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n4()
