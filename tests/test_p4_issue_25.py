"""Regression tests for red-team issue #25 (NFR-5, FR-20/NFR-6): data stores and ingress in the Terraform deployment
had no public-access block, no versioning, no access or flow logs, no point-in-time recovery and no customer-managed
encryption.

The checks are written as rules over every resource of a type, not only the ones the red team listed, so a bucket,
table, queue or log group added later is held to the same bar. Static checks on infra/terraform/*.tf; checkov itself
is run separately (see the PR).
"""

from __future__ import annotations

import re

from test_p4_issue_20 import _attr, _block, _blocks, _terraform

ACCESS_LOG_BUCKET = "access_logs"  # S3 server access logs can only be written to an SSE-S3 bucket


def _names(code: str, resource_type: str) -> list[str]:
    return re.findall(rf'resource\s+"{resource_type}"\s+"(\w+)"\s*\{{', code)


def _companion(code: str, resource_type: str, bucket: str) -> str:
    """The body of the `resource_type` block that points at aws_s3_bucket.<bucket>."""
    found = [
        body
        for body in _blocks(code, rf'resource\s+"{resource_type}"\s+"\w+"')
        if re.search(rf"^\s*bucket\s*=\s*aws_s3_bucket\.{bucket}\.(id|bucket)\s*$", body, re.M)
    ]
    assert len(found) == 1, f"aws_s3_bucket.{bucket} needs exactly one {resource_type}, found {len(found)}"
    return found[0]


def _project_key_ref(value: str) -> bool:
    return re.fullmatch(r"aws_kms_key\.data\.arn", value) is not None


# --- S3 ---------------------------------------------------------------------------------------------------------


def test_issue25_every_bucket_blocks_public_access():
    code = _terraform()
    for bucket in _names(code, "aws_s3_bucket"):
        block = _companion(code, "aws_s3_bucket_public_access_block", bucket)
        for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
            assert _attr(block, flag) == "true", f"{bucket}: {flag} must be true"


def test_issue25_every_bucket_is_versioned():
    code = _terraform()
    for bucket in _names(code, "aws_s3_bucket"):
        versioning = _block(_companion(code, "aws_s3_bucket_versioning", bucket), r"\bversioning_configuration")
        assert _attr(versioning, "status") == '"Enabled"', bucket


def test_issue25_data_buckets_are_encrypted_with_the_project_key():
    code = _terraform()
    for bucket in _names(code, "aws_s3_bucket"):
        config = _companion(code, "aws_s3_bucket_server_side_encryption_configuration", bucket)
        default = _block(config, r"\bapply_server_side_encryption_by_default")
        if bucket == ACCESS_LOG_BUCKET:
            assert _attr(default, "sse_algorithm") == '"AES256"'
            continue
        assert _attr(default, "sse_algorithm") == '"aws:kms"', bucket
        assert _project_key_ref(_attr(default, "kms_master_key_id")), bucket
        assert _attr(_block(config, r"\brule"), "bucket_key_enabled") == "true", bucket


def test_issue25_data_buckets_write_access_logs():
    code = _terraform()
    data_buckets = [name for name in _names(code, "aws_s3_bucket") if name != ACCESS_LOG_BUCKET]
    assert {"outputs", "static_app"} <= set(data_buckets)
    for bucket in data_buckets:
        logging = _companion(code, "aws_s3_bucket_logging", bucket)
        assert _attr(logging, "target_bucket") == f"aws_s3_bucket.{ACCESS_LOG_BUCKET}.id", bucket


# --- SQS, DynamoDB, CloudWatch Logs -----------------------------------------------------------------------------


def test_issue25_every_queue_is_encrypted():
    code = _terraform()
    queues = _blocks(code, r'resource\s+"aws_sqs_queue"\s+"\w+"')
    assert len(queues) >= 2
    for queue in queues:
        assert re.search(r"^\s*sqs_managed_sse_enabled\s*=\s*true\s*$", queue, re.M) or re.search(
            r"^\s*kms_master_key_id\s*=", queue, re.M
        ), f"unencrypted queue:\n{queue}"


def test_issue25_every_table_has_point_in_time_recovery_and_the_project_key():
    code = _terraform()
    tables = _names(code, "aws_dynamodb_table")
    assert {"state", "leases", "tasks", "robot_status", "decision_log"} <= set(tables)
    for name in tables:
        table = _block(code, rf'resource\s+"aws_dynamodb_table"\s+"{name}"')
        assert _attr(_block(table, r"\bpoint_in_time_recovery"), "enabled") == "true", name
        encryption = _block(table, r"\bserver_side_encryption")
        assert _attr(encryption, "enabled") == "true", name
        assert _project_key_ref(_attr(encryption, "kms_key_arn")), name


def test_issue25_every_log_group_is_encrypted_and_kept_a_year():
    code = _terraform()
    groups = _blocks(code, r'resource\s+"aws_cloudwatch_log_group"\s+"\w+"')
    assert len(groups) >= 2, "the app log group and the API access log group"
    for group in groups:
        assert int(_attr(group, "retention_in_days")) >= 365, group
        assert _project_key_ref(_attr(group, "kms_key_id")), group


# --- Ingress and network traceability ---------------------------------------------------------------------------


def test_issue25_api_stage_writes_access_logs():
    stage = _block(_terraform(), r'resource\s+"aws_apigatewayv2_stage"\s+"default"')
    settings = _block(stage, r"\baccess_log_settings")
    assert re.fullmatch(r"aws_cloudwatch_log_group\.\w+\.arn", _attr(settings, "destination_arn"))
    assert "$context.requestId" in settings and "$context.status" in settings


def test_issue25_vpc_has_flow_logs():
    code = _terraform()
    logs = [body for body in _blocks(code, r'resource\s+"aws_flow_log"\s+"\w+"') if "aws_vpc.main.id" in body]
    assert len(logs) == 1
    assert _attr(logs[0], "traffic_type") == '"ALL"'


# --- The key itself ---------------------------------------------------------------------------------------------


def test_issue25_project_key_rotates_and_lets_the_services_use_it():
    key = _block(_terraform(), r'resource\s+"aws_kms_key"\s+"data"')
    assert _attr(key, "enable_key_rotation") == "true"
    # The services must be able to use the key, or the app breaks on the first apply: DynamoDB and S3 for any
    # principal in this account that may already use the table or bucket (the same rule as the AWS-managed
    # aws/dynamodb and aws/s3 keys), and CloudWatch Logs for this account's log groups.
    assert '"kms:ViaService"' in key
    assert "dynamodb.${var.aws_region}.amazonaws.com" in key
    assert "s3.${var.aws_region}.amazonaws.com" in key
    assert '"kms:CallerAccount"' in key
    assert "logs.${var.aws_region}.amazonaws.com" in key
