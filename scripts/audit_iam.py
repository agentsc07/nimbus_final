"""Configuration and secrets audit for NFR-5 (least-privilege IAM, no secrets in code). Verified in experiment E6 by an
audit, not a runtime measurement.

    python scripts/audit_iam.py                 # prints a report, exit code 1 if anything fails
    python scripts/audit_iam.py --out docs/iam-audit.md
    python scripts/audit_iam.py --history       # also scan every line ever added on any ref (`git log -p --all`)

Checks:
  1. IAM policies in infra/**/*.json and infra/**/*.tf: no `"*"` action, no `service:*` action, no `"*"` resource
     (alone or inside a list), no Allow with NotAction / NotResource. Statements are checked with or without a Sid.
     Anything not in JUSTIFIED fails.
  2. No secrets in tracked files: every text file `git ls-files` lists, whatever its name or folder (`.env*`, `.tfvars`,
     `.jsonl`, `.csv`, `.log`, results/, runs/, data.prev/, tests/ ...). When ROOT is not the top of a git checkout,
     every file under ROOT is scanned instead. Binary files (a NUL byte in the first 8 KB) are skipped.
     Patterns: AWS key ids and secret keys (any case of AWS_SECRET_ACCESS_KEY), private keys, GitHub and Slack tokens,
     hard-coded passwords, literal Nimbus API tokens, and literal bearer tokens.
  3. With --history, the same patterns over every added line in the history of every ref.

Allowlist (reported as allowlisted, not as findings):
  - placeholder values: AKIAIOSFODNN7EXAMPLE and wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY (AWS documentation examples),
    any value containing EXAMPLE, PLACEHOLDER, CHANGEME / CHANGE-ME / CHANGE_ME, REDACTED or starting with YOUR, and
    values made of at most two distinct characters after their prefix (AKIAXXXXXXXXXXXXXXXX);
  - explicit test fixtures: a line that carries the marker `secret-scan: allow`, and the (file, value) pairs in
    FIXTURES (fixtures committed before the marker existed, which stay in git history).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (file name, statement id or action) -> why a wildcard is acceptable. Anything not listed fails the audit.
JUSTIFIED = {
    ("p3-dev-policy.json", "bedrock:InvokeModel"): "Bedrock invocation resources are foundation-model and inference-profile ARNs that differ per region",
    ("p3-dev-policy.json", "DynamoDbListTables"): "dynamodb:ListTables does not support resource-level permissions in IAM",
}
# Patterns with a capture group check group 1 against the placeholder allowlist; the others check the whole match.
SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "AWS secret key": re.compile(r"(?i)\b(?:aws_?)?secret_?access_?key[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9/+=]{30,})"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "hard-coded password": re.compile(r"(?i)\bpassword\s*=\s*['\"]([^'\"\s]{6,})['\"]"),
    "Nimbus API token": re.compile(r"(?i)\bNIMBUS_[A-Z_]*TOKEN[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9._~+/-]{16,})"),
    "bearer token": re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/-]{24,}=*)"),
}
PLACEHOLDER_VALUES = {"AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}
PLACEHOLDER_WORDS = ("EXAMPLE", "PLACEHOLDER", "CHANGEME", "CHANGE-ME", "CHANGE_ME", "REDACTED")
ALLOW_MARKER = "secret-scan: allow"
FIXTURES = {  # (path, value): why it is not a secret
    ("tests/test_ms2_audit.py", "AKIAABCDEFGHIJKLMNOP"): "fake key id this test planted before the marker existed",
}
SKIP_FILES = {"audit_iam.py", "iam-audit.md"}           # this scanner's own patterns and report
WALK_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".terraform"}  # non-git fallback only
MAX_BYTES = 20_000_000


# --- IAM -------------------------------------------------------------------------------------------------------------

def iam_findings() -> list[dict]:
    out = []
    for path in sorted((ROOT / "infra").rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        sts = doc.get("Statement") if isinstance(doc, dict) else None
        for n, st in enumerate([sts] if isinstance(sts, dict) else (sts or []), 1):
            if isinstance(st, dict):
                out += _check(path.name, st.get("Sid") or f"(no Sid, statement {n})", st.get("Effect"),
                              st.get("Action"), st.get("Resource"), st.get("NotAction"), st.get("NotResource"))
    for path in sorted((ROOT / "infra").rglob("*.tf")):
        for st in _tf_statements(path.read_text(encoding="utf-8")):
            out += _check(path.name, st["Sid"], st["Effect"], st["Action"], st["Resource"], st["NotAction"], st["NotResource"])
    return out


def _check(file: str, sid: str, effect, actions, resources, not_actions=None, not_resources=None) -> list[dict]:
    if effect != "Allow":
        return []
    acts = [actions] if isinstance(actions, str) else list(actions or [])
    res = [resources] if isinstance(resources, str) else list(resources or [])
    found = []
    for a in acts:
        if a == "*" or a.endswith(":*"):
            found.append({"file": file, "statement": sid, "problem": f"wildcard action {a}", "justified": JUSTIFIED.get((file, a))})
    if "*" in res:
        justified = JUSTIFIED.get((file, sid)) or next((JUSTIFIED[(file, a)] for a in acts if (file, a) in JUSTIFIED), None)
        found.append({"file": file, "statement": sid, "problem": "wildcard resource", "justified": justified})
    for key, value in (("NotAction", not_actions), ("NotResource", not_resources)):
        if value:
            found.append({"file": file, "statement": sid, "problem": f"Allow with {key}", "justified": JUSTIFIED.get((file, sid))})
    return found


def _tf_skeleton(text: str) -> tuple[str, list[tuple[int, int]]]:
    """The text with comments blanked (newlines kept), and the (open, close) offsets of every `{...}` outside strings."""
    out, blocks, stack = list(text), [], []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':                                        # string: skip escapes and ${...} interpolations
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 2
                    continue
                if text.startswith("${", i):
                    depth, i = 1, i + 2
                    while i < n and depth:
                        depth += {"{": 1, "}": -1}.get(text[i], 0)
                        i += 1
                    continue
                i += 1
        elif c == "#" or text.startswith("//", i) or text.startswith("/*", i):
            end = text.find("*/", i + 2) + 2 if text.startswith("/*", i) else text.find("\n", i)
            end = n if end < 2 or end == -1 else end
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        elif c == "{":
            stack.append(i)
        elif c == "}" and stack:
            blocks.append((stack.pop(), i))
        i += 1
    return "".join(out), blocks


_TF_KEY = re.compile(r'(?:^|[\s,{])"?(Sid|Effect|Action|NotAction|Resource|NotResource)"?\s*[=:]')
_TF_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _tf_statements(text: str) -> list[dict]:
    """Every block whose own (not nested) keys include Effect, i.e. every IAM-style statement, with or without a Sid,
    whether written in HCL (`jsonencode`) or as JSON inside the .tf file."""
    skel, blocks = _tf_skeleton(text)
    statements = []
    for start, end in blocks:
        own = list(skel[start + 1:end])
        for s, e in blocks:                                  # blank nested blocks so their keys are not this block's
            if start < s and e < end:
                for j in range(s + 1 - start - 1, e - start - 1):
                    own[j] = " "
        own_text = "".join(own)
        keys = list(_TF_KEY.finditer(own_text))
        if not any(k.group(1) == "Effect" for k in keys):
            continue
        values: dict[str, list[str]] = {}
        for k, nxt in zip(keys, keys[1:] + [None]):
            values[k.group(1)] = _TF_STRING.findall(own_text[k.end():nxt.start() if nxt else len(own_text)])
        effect = (values.get("Effect") or ["Allow"])[0]      # a computed Effect counts as Allow
        sid = (values.get("Sid") or [None])[0] or f"(no Sid, line {text.count(chr(10), 0, start) + 1})"
        statements.append({"Sid": sid, "Effect": effect, "Action": values.get("Action", []), "Resource": values.get("Resource", []),
                           "NotAction": values.get("NotAction", []), "NotResource": values.get("NotResource", [])})
    return statements


# --- secrets ---------------------------------------------------------------------------------------------------------

def _is_placeholder(value: str) -> bool:
    upper = value.upper()
    if value in PLACEHOLDER_VALUES or any(w in upper for w in PLACEHOLDER_WORDS) or upper.startswith("YOUR"):
        return True
    body = value[4:] if value[:4] in ("AKIA", "ASIA") else value
    return len(set(body)) <= 2


def _line_hits(text: str, file: str):
    """(line number, kind, allowlist reason or None) for every pattern match in `text`, which comes from `file`."""
    lines = text.split("\n")
    for kind, pat in SECRET_PATTERNS.items():
        for m in pat.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            value = m.group(1) if pat.groups else m.group(0)
            reason = ("marker" if ALLOW_MARKER in lines[line_no - 1] else
                      "fixture" if (file, value) in FIXTURES else
                      "placeholder" if _is_placeholder(value) else None)
            yield line_no, kind, reason


def _tracked_files() -> list[Path]:
    """Files git tracks when ROOT is the top of a git checkout; otherwise every file under ROOT."""
    try:
        top = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
        if top and Path(top).resolve() == ROOT.resolve():
            raw = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
            return [ROOT / p for p in sorted(raw.decode("utf-8", "surrogateescape").split("\0")) if p]
    except (OSError, subprocess.CalledProcessError):
        pass
    return [p for p in sorted(ROOT.rglob("*")) if not WALK_SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def _scan_files() -> tuple[list[dict], list[dict], list[str]]:
    """(findings, allowlisted hits, files skipped for size) over the tracked text files."""
    findings, allowed, too_big = [], [], []
    for path in _tracked_files():
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            if path.stat().st_size > MAX_BYTES:
                too_big.append(rel)
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue                                         # binary
        for line, kind, reason in _line_hits(data.decode("utf-8", errors="ignore"), rel):
            hit = {"file": rel, "line": line, "kind": kind}
            if reason:
                allowed.append({**hit, "allowlisted": reason})
            else:
                findings.append(hit)
    return findings, allowed, too_big


def secret_findings() -> list[dict]:
    return _scan_files()[0]


def history_findings() -> list[dict]:
    """Secrets on lines added in any commit reachable from any ref (`git log -p --all`), same patterns and allowlist."""
    out = []
    cmd = ["git", "-C", str(ROOT), "log", "-p", "--all", "--no-color", "--no-ext-diff", "--unified=0", "--format=commit %H"]
    commit = file = None
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            if line.startswith("commit "):
                commit = line[7:19]
            elif line.startswith("+++ "):
                file = line[6:] if line.startswith("+++ b/") else None
            elif line.startswith("+") and file and Path(file).name not in SKIP_FILES:
                for _, kind, reason in _line_hits(line[1:], file):
                    if not reason:
                        out.append({"commit": commit, "file": file, "kind": kind})
    if proc.returncode:
        raise RuntimeError(f"git log failed with exit code {proc.returncode}")
    return out


def run(history: bool = False) -> tuple[str, bool]:
    iam = iam_findings()
    secrets, allowed, too_big = _scan_files()
    hist = history_findings() if history else []
    bad_iam = [f for f in iam if not f["justified"]]
    lines = ["# IAM and secrets audit (NFR-5)", "", f"- IAM statements with a wildcard: {len(iam)} ({len(bad_iam)} unjustified)",
             f"- Secrets found in tracked files: {len(secrets)}",
             f"- Allowlisted placeholder / test-fixture hits: {len(allowed)}"]
    if history:
        lines.append(f"- Secrets found in git history (all refs): {len(hist)}")
    if too_big:
        lines.append(f"- Not scanned (over {MAX_BYTES // 1_000_000} MB): {', '.join(too_big)}")
    lines.append("")
    if iam:
        lines += ["| file | statement | problem | justification |", "|---|---|---|---|"]
        lines += [f"| {f['file']} | {f['statement']} | {f['problem']} | {f['justified'] or '**NONE**'} |" for f in iam]
        lines.append("")
    if secrets:
        lines += ["| file | line | kind |", "|---|---|---|"] + [f"| {s['file']} | {s['line']} | {s['kind']} |" for s in secrets] + [""]
    if allowed:
        lines += ["| allowlisted file | line | kind | why |", "|---|---|---|---|"]
        lines += [f"| {s['file']} | {s['line']} | {s['kind']} | {s['allowlisted']} |" for s in allowed] + [""]
    if hist:
        lines += ["| commit | file | kind |", "|---|---|---|"] + [f"| {h['commit']} | {h['file']} | {h['kind']} |" for h in hist] + [""]
    ok = not bad_iam and not secrets and not hist
    lines.append("**RESULT: PASS**" if ok else "**RESULT: FAIL**")
    return "\n".join(lines) + "\n", ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--history", action="store_true", help="also scan every added line in `git log -p --all`")
    a = ap.parse_args(argv)
    report, ok = run(history=a.history)
    print(report)
    if a.out:
        Path(a.out).write_text(report, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
