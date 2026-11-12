"""NFR-5 audit tooling: it passes on the repository and fails on a bad policy or a leaked key."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_iam  # noqa: E402


def test_repository_passes_the_audit_and_a_report_is_written(tmp_path):
    report, ok = audit_iam.run()
    assert ok, report
    out = tmp_path / "r.md"
    assert audit_iam.main(["--out", str(out)]) == 0 and "RESULT: PASS" in out.read_text()


def test_wildcards_in_json_and_terraform_are_caught(tmp_path, monkeypatch):
    (tmp_path / "infra" / "iam").mkdir(parents=True)
    (tmp_path / "infra" / "iam" / "bad.json").write_text(json.dumps({"Statement": [
        {"Sid": "Everything", "Effect": "Allow", "Action": "*", "Resource": "*"},
        {"Sid": "Svc", "Effect": "Allow", "Action": ["s3:*"], "Resource": "arn:aws:s3:::b/*"},
        {"Sid": "Fine", "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::b/*"}]}))
    (tmp_path / "infra" / "x.tf").write_text('''
      Statement = [
        {
          Sid    = "TfBad"
          Effect = "Allow"
          Action = ["dynamodb:*"]
          Resource = "*"
        },
        {
          Sid    = "TfFine"
          Effect = "Allow"
          Action = ["sqs:ReceiveMessage"]
          Resource = aws_sqs_queue.q.arn
        },
        {
          # no Sid, and the wildcard is one entry of a list
          Effect   = "Allow"
          Action   = ["s3:GetObject"]
          Resource = ["arn:aws:s3:::b/*", "*"]
        },
      ]
    ''')
    monkeypatch.setattr(audit_iam, "ROOT", tmp_path)
    found = audit_iam.iam_findings()
    assert {(f["statement"], f["problem"]) for f in found} >= {("Everything", "wildcard action *"), ("Everything", "wildcard resource"),
                                                              ("Svc", "wildcard action s3:*"), ("TfBad", "wildcard action dynamodb:*")}
    assert any(f["statement"].startswith("(no Sid") and f["problem"] == "wildcard resource" for f in found)
    assert not any(f["statement"] in ("Fine", "TfFine") for f in found)
    assert audit_iam.run()[1] is False


# Fixture values are assembled at run time so this file itself holds no key-shaped literal for the scanner to find.
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_SECRET = "Zq3" + "x9Lp2Wv8Rk5Tn1Hs7Jd4Fg6Bm0Cy2Ea8Ui"


def test_secrets_are_caught_anywhere_but_placeholders_and_marked_fixtures_are_not(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(f'KEY = "{FAKE_KEY}"\nTOKEN = "ghp_' + "a" * 36 + '"\npassword = "hunter22hunter"\n')
    (tmp_path / "ok.py").write_text('KEY = os.environ["AWS_ACCESS_KEY_ID"]\nPLACEHOLDER = "AKIAXXXXXXXXXXXXXXXX"\n'
                                    'DOC_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(f'K = "{FAKE_KEY}"\n')                                  # tests are scanned too
    (tmp_path / "tests" / "fixture.py").write_text(f'K = "{FAKE_KEY}"  # secret-scan: allow (test fixture)\n')
    (tmp_path / ".env").write_text(f"AWS_SECRET_ACCESS_KEY={FAKE_SECRET}\n")                          # upper case, no suffix
    (tmp_path / "prod.tfvars").write_text(f'access_key = "{FAKE_KEY}"\n')
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "events.jsonl").write_text(json.dumps({"key": FAKE_KEY}) + "\n")
    monkeypatch.setattr(audit_iam, "ROOT", tmp_path)
    kinds = {(f["file"], f["kind"]) for f in audit_iam.secret_findings()}
    assert kinds == {("app.py", "AWS access key id"), ("app.py", "GitHub token"), ("app.py", "hard-coded password"),
                     ("tests/t.py", "AWS access key id"), (".env", "AWS secret key"),
                     ("prod.tfvars", "AWS access key id"), ("results/events.jsonl", "AWS access key id")}
    report, ok = audit_iam.run()
    assert not ok and "tests/fixture.py | 1 | AWS access key id | marker" in report


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_history_mode_finds_a_secret_that_was_removed(tmp_path, monkeypatch):
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    (tmp_path / "creds.txt").write_text(f"key {FAKE_KEY}\n")
    subprocess.run(git + ["add", "creds.txt"], check=True)
    subprocess.run(git + ["commit", "-qm", "add"], check=True)
    (tmp_path / "creds.txt").write_text("nothing here\n")
    subprocess.run(git + ["commit", "-qam", "remove"], check=True)
    monkeypatch.setattr(audit_iam, "ROOT", tmp_path)
    assert audit_iam.secret_findings() == []
    assert [(h["file"], h["kind"]) for h in audit_iam.history_findings()] == [("creds.txt", "AWS access key id")]
    assert audit_iam.run(history=True)[1] is False
