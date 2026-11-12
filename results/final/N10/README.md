# N10: Requester app and operator console

- **Claim:** Operator cancel and pause calls are acknowledged by the cloud control API well within 5 s, and SC-1 reaches 'completed' through the requester API when the edge completion is simulated.
- **PRD pass bar:** SC-1 completes from app; cancel or override reaches robots within 5 s (FR-21, FR-22).
- **Measured:** local in-process server.py on 127.0.0.1: cloud control-API round trip (POST /tasks/{id}/control) cancel p95 0.057 s, pause p95 0.055 s, max 0.062 s; 40/40 acknowledged within 5 s with the expected status; 40/40 leased tasks got a new stop-lease version from the cloud; stop-lease delivery to edge/robots not measured; SC-1 with simulated edge completion: final status completed
- **Verdict:** PASS (cloud side only; edge/robot receipt not measured)
- **Source of numbers:** measured (local in-process server.py on 127.0.0.1, model rule-based stand-in)
- **Command:** `python results/final/N10/run_n10.py --no-video`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:29:03Z to 2026-11-12T08:29:13Z

## Plots

![cancel_latency_cdf](plots/cancel_latency_cdf.png)

## Notes

- Measured: the HTTP round trip of the operator's control call and the status/lease version the cloud reports afterwards. Not measured: publication of the stop lease to an edge, an edge acknowledgement, or a robot stopping; no edge or robot runs in this experiment. The FR-22 'reaches robots within 5 s' part is therefore untested here.
- Target: local in-process server.py on 127.0.0.1. With no NIMBUS_CLOUD_URL the runner starts server.py in-process on 127.0.0.1 with NIMBUS_AUTH_DISABLED=1 (local only); with NIMBUS_CLOUD_URL set it exits with status 2 if GET /health fails, instead of silently measuring a local server. Nothing here ran against the deployed AWS cloud.
- Each paused task is then cancelled (untimed, cleanup_cancel_http_status in cancel.csv) so its robot is free and the next request can be leased rather than queued; Measured counts how many timed calls hit a leased task.
- SC-1 is driven through the requester API; the OUTPUT_READY that completes it is posted by this script with the task's lease version (simulated edge completion). sc1.json records each step.
- Verdict rule: PASS iff every control call is acknowledged with the expected status within 5 s and SC-1 reaches 'completed'; the PASS covers the cloud side only.
- Video step skipped (--no-video). sc1_completed_flow.webm and cancel_override_flow.webm predate this change and were not re-recorded (earlier version of this runner; its SC-1 OUTPUT_READY was also posted by the script).
- demo_completed_flow.webm and demo_cancel_flow.webm come from scripts/record_n10_videos.py, not from this runner, and predate this change. The recording loads the operator page, which fetches fonts and three.js from public CDNs.
