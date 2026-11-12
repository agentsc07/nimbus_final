# N7: Security and privacy audit

- **Claim:** The repository declares least-privilege IAM, holds no secrets in tracked source, uses only synthetic data, and its WAN contracts carry images only by reference in OUTPUT_READY.
- **PRD pass bar:** No wildcard IAM on data; no secrets in code; 100% synthetic data; images only inside OUTPUT_READY (NFR-5).
- **Measured:** 10/10 static checks passed; 0 unjustified IAM wildcards (2 wildcard statements); 0 secret-pattern hits in tracked source; 0 manifest problems; 0 PII-pattern hits; 0 inline image/binary schema fields
- **Verdict:** PASS
- **Source of numbers:** static_audit (static scan of this repository's working tree; no git history, no deployed account)
- **Command:** `python results/final/N7/run_n7.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:26:42Z to 2026-11-12T08:27:03Z

## Plots

![security_checklist](plots/security_checklist.png)

## Notes

- Source is `static_audit`: a scan of the files in this checkout. It does not inspect git history, the deployed IAM roles, or traffic on the wire, so it shows what the repository declares, not what a running system sends.
- SEC-07 uses scripts/audit_data.py's PII patterns (e-mail, phone, national id, medical record number, date of birth) over every dataset the manifest lists (not only traces/). SEC-06 checks the manifest itself, comparing POSIX paths.
- SEC-10 replaces an earlier check that string-matched contracts/topics.md for the word 'image' (it failed on a documented upload content type). It now walks every contracts/*.schema.json for properties named like image/photo/frame/base64/bytes or declaring contentEncoding, contentMediaType image/* or format binary/byte.
- Limitation of SEC-09/SEC-10: the escalation schema's payload objects do not set additionalProperties to false, so the schemas alone do not forbid an extra inline-image key in, say, an UNEXPECTED_EVENT payload; runtime enforcement is not audited here.
- Verdict rule: PASS iff every check in summary.csv passes; findings.json lists what each check found.
