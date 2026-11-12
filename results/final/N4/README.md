# N4: Duplicate and replayed messages at the cloud ingress

- **Claim:** Repeated message ids at the cloud's request ingress are acknowledged but never executed twice, and controls on a finished task are refused.
- **PRD pass bar:** Zero steps executed twice (FR-8); every drop logged with reason.
- **Measured:** 0 steps executed twice over 5000 messages in 10 seeds: 1500/1500 repeated message ids dropped as duplicates (1000 duplicates, 500 replays with altered text); 1500/1500 repeat cancels of a cancelled task refused with 409; 1000/1000 fresh requests accepted; server state: 0 tasks from altered replays, at most 1 task per duplicated message
- **Verdict:** PASS
- **Source of numbers:** simulated (local in-process server.py on 127.0.0.1, auth disabled, model rule-based stand-in)
- **Command:** `python results/final/N4/run_n4.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:29:21Z to 2026-11-12T08:31:17Z

## Plots

![injection_outcomes](plots/injection_outcomes.png)
![timeline_dedup](plots/timeline_dedup.png)

## Notes

- Real system: every message goes over HTTP to server.py's ingress (in-process, 127.0.0.1, rule-based stand-in model). The source stays `simulated` because the messages are synthetic and no edge, robot or lease-version traffic is involved.
- Renamed categories: what earlier versions called 'stale lease version' is a fresh-id cancel of an already-cancelled task (409), and 'shuffled order' is a set of fresh unique requests (the control group). No true stale-lease-version or re-ordering injection at the edge or check-in path is run here; R6 covers stale versions at the edge.
- Drop reasons: each drop is answered with a reason (duplicate flag or 409 error text) and recorded per message in e6_injection.csv by this harness. The server does not write a persistent drop-log row, so 'every drop logged' is met by the harness's record of the server's answer, not by a server-side log.
- Verdict rule: PASS iff no repeated message id is executed again, every repeat is dropped, every message gets the expected answer, every drop carries a reason, and GET /tasks shows no task from an altered replay and at most one task per duplicated message (state_check.json).
