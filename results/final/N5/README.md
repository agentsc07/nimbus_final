# N5: Selective sharing

- **Claim:** MapState tells every affected cluster about a map event (recall 100%) and few unaffected ones.
- **PRD pass bar:** Recall 100% (every affected cluster told) (FR-11); high precision (few unaffected).
- **Measured:** recall 100.0% (TP 441, FN 0), precision 100.0% (FP 0) over 600 cluster decisions for 300 sampled events; 72 unique (zone, type) events, 15/15 zones, 10 distinct lease layouts, 39 events in a zone a lease from the other wing routes through
- **Verdict:** PASS
- **Source of numbers:** simulated (in-process cloud.mapstate.MapState on pack hospital_sim6, sampled events)
- **Command:** `python results/final/N5/run_n5.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:26:32Z to 2026-11-12T08:26:33Z

## Plots

![confusion_matrix](plots/confusion_matrix.png)
![precision_recall](plots/precision_recall.png)

## Notes

- The seed's RNG now draws the events (zone and type) and the live leases; earlier versions ran one fixed list of 30 events ten times, so the ten seeds were copies.
- The expected set encodes the FR-11 rule (a cluster is affected if the zone is in its area or a shared area, or a live lease of it routes through the zone) straight from the pack's topology document, independently of MapState's code. This checks the implementation against the rule, not whether the rule tells the right people.
- Operator and requester notification are not evaluated (earlier versions reported a constant 100% for them).
- Verdict rule: PASS iff no affected cluster is missed (FN = 0); precision is reported.
