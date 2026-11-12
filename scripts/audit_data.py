"""Synthetic-data-only check of the dataset manifest (PRD NFR-5, verified in E6).

    python scripts/audit_data.py                 # exit code 1 if anything fails

Passes when: every dataset in evaluation/manifest.json is declared synthetic, or is a network measurement that says it holds no
personal data; every file under evaluation/ and traces/ is listed in the manifest; no listed file contains anything that looks like
personal data: e-mail address; phone number (US style, or Indian: +91 / 0091 / 0 prefix or a bare 10-digit number starting
with 6-9); national id (US SSN, Aadhaar written in groups of four); medical record number (MRN, UHID, hospital/patient id,
14-digit ABHA number); a patient name ("patient Ravi Kumar", "patient: Mrs. Rao", a simple capitalised-name heuristic);
date of birth. The patterns are heuristics: a pass means none of them matched, not that a file is free of personal data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Capitalised words that commonly follow "patient" in the synthetic hospital requests but are not names.
_NOT_NAMES = ("Monitor|Monitors|Transport|Transfer|Lift|Bed|Beds|Room|Ward|Care|Zone|Area|Corridor|Trolley|Gurney|"
              "Wheelchair|Records|Record|Services|Service|Safety|Flow|Unit|Admission|Discharge|Id|ID|No|Number")
PII = {
    "e-mail address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone number": re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -])?(?:\(?\d{3}\)?[ -]?)\d{3}[ -]\d{4}(?!\d)"),
    "Indian phone number": re.compile(r"(?<![\w.+-])(?:(?:\+91|0091)[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?![\w.])"),
    "national id": re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b[2-9]\d{3}[ -]\d{4}[ -]\d{4}\b"),
    "medical record number": re.compile(
        r"(?i)\b(?:mrn|uhid|medical record(?: number| no\.?)?|hospital (?:no\.?|number|id)|patient id)\s*[:#.-]?\s*[a-z]{0,4}[-/]?\d{4,}"
        r"|\b\d{2}-\d{4}-\d{4}-\d{4}\b"),
    "patient name": re.compile(r"\b[Pp]atient(?:'s)?(?:\s+name)?\s*[:=-]?\s+(?:(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+)?"
                               rf"(?!(?:{_NOT_NAMES})\b)[A-Z][a-z]{{2,}}(?:\s+[A-Z][a-z]{{2,}})?\b"),
    "date of birth": re.compile(r"(?i)\b(?:dob|date of birth)\b"),
}


def audit(root: Path = ROOT) -> list[str]:
    problems = []
    mpath = root / "evaluation" / "manifest.json"
    if not mpath.exists():
        return ["evaluation/manifest.json is missing"]
    manifest = json.loads(mpath.read_text())
    listed = set()
    for d in manifest["datasets"]:
        listed.add(d["path"])
        if d.get("real_patient_data"):
            problems.append(f"{d['path']}: declares real patient data")
        elif not (d.get("synthetic") is True or d.get("contains_personal_data") is False):
            problems.append(f"{d['path']}: must be synthetic, or state that it holds no personal data")
        if not (root / d["path"]).exists():
            problems.append(f"{d['path']}: listed but not found")
    for base in ("evaluation", "traces"):
        for f in sorted((root / base).rglob("*")) if (root / base).exists() else []:
            rel = f.relative_to(root).as_posix()        # manifest paths use '/', also on Windows
            if f.is_file() and rel not in listed and f.name != "manifest.json":
                problems.append(f"{rel}: not listed in the manifest")
    for path in sorted(listed):
        f = root / path
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="ignore")
            for kind, pat in PII.items():
                m = pat.search(text)
                if m:
                    problems.append(f"{path}: looks like it contains a {kind} ({m.group(0)[:20]!r})")
    return problems


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    problems = audit()
    print("RESULT: PASS" if not problems else "RESULT: FAIL\n" + "\n".join(f"- {p}" for p in problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
