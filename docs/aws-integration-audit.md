# AWS Infrastructure and Service Integration Audit

**Target Environment:** AWS Account `930124786284` | Region `ap-south-1`  
**ECS Service:** `nimbus-ds252-service` (`nimbus-ds252-cluster`)  
**Terraform Base:** `infra/terraform/main.tf`, `infra/terraform/variables.tf`  
**Audit Status:** P4 Red-Team Remediation Complete (C2, C3, C4, Addendum 2)

---

## 1. AWS IoT Core Integration Audit

| Property | Application Design | Terraform Implementation | Status / Finding |
| :--- | :--- | :--- | :--- |
| **MQTT Client** | `PahoMQTTClient` in `mqtt_transport.py` | Configured via `var.iot_endpoint` | Clean fallback on connect timeout |
| **Subscribed Topics** | `nimbus/+/escalation`<br>`nimbus/+/checkin` | IoT Policy allows topic filters `arn:aws:iot:ap-south-1:930124786284:topicfilter/nimbus/*` | Validated; wildcard topicfilter aligns with single-level `+` in Paho |
| **Published Topics** | `nimbus/{cluster_id}/lease`<br>`nimbus/{cluster_id}/heartbeat` | IoT Policy allows `arn:aws:iot:ap-south-1:930124786284:topic/nimbus/*` | Validated; exact topic publishing permitted |
| **Client Authentication**| X.509 Certificate mutual TLS / AWS SigV4 | IoT Thing Policy attached to container certificate | Required for physical edge robots; disabled by default in synthetic runs (`NIMBUS_MQTT_DISABLED=1`) |
| **Failure Tolerance** | Non-blocking background connect; non-fatal if broker is absent | Application logs warning and operates over HTTP ingress if MQTT is unreachable | **Fixed (H5)**: Startup crash eliminated |

---

## 2. Amazon SQS Integration Audit

| Property | Configuration | Code Reference | Audit Findings |
| :--- | :--- | :--- | :--- |
| **Queue Name** | `nimbus-ds252-escalations` | `cloud/aws_sqs.py` / `infra/terraform/main.tf` | Standard queue provisioned |
| **Visibility Timeout** | 300 seconds | AWS SDK default overridden to 300s | SQS visibility timeout exceeds maximum Bedrock LLM round-trip timeout (15s) and edge decision loop (30s), preventing premature duplicate redelivery |
| **Dead-Letter Queue** | `nimbus-ds252-escalations-dlq` | `redrive_policy` (maxReceiveCount = 5) | Prevents poison message loops from exhausting ECS CPU |
| **IAM Permissions** | `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` | Task execution IAM policy | Scoped strictly to queue ARN `arn:aws:sqs:ap-south-1:930124786284:nimbus-ds252-escalations*` |

---

## 3. Amazon EventBridge Integration Audit

| Property | Application Status | Audit Evaluation | Recommendation / Ownership |
| :--- | :--- | :--- | :--- |
| **Event Bus** | `default` bus rule defined in Terraform | No active `boto3.client("events").put_events` calls found in P4 runtime code (`server.py`) | **P3 Ownership Handoff**: Cloud orchestrator currently records decision log entries directly to DynamoDB rather than publishing to EventBridge. The Terraform rule is retained for future decoupled analytics, but not relied upon for core task leasing. |

---

## 4. IAM Least-Privilege Audit

| IAM Action Set | Resource Scope | Audit Finding | Remediation Applied |
| :--- | :--- | :--- | :--- |
| `dynamodb:GetItem`<br>`dynamodb:PutItem`<br>`dynamodb:UpdateItem`<br>`dynamodb:DeleteItem`<br>`dynamodb:Query`<br>`dynamodb:Scan` | `arn:aws:dynamodb:ap-south-1:930124786284:table/nimbus-ds252-*` | Scoped to the 5 project tables | Least privilege verified |
| `dynamodb:TransactWriteItems`<br>`dynamodb:TransactGetItems`<br>`dynamodb:DescribeTable` | `arn:aws:dynamodb:ap-south-1:930124786284:table/nimbus-ds252-*` | Previously missing in Terraform policy; led to runtime permission errors on atomic lease increments | **Fixed (C4)**: Explicitly added to `aws_iam_policy.app_dynamo` |
| `bedrock:InvokeModel` | `arn:aws:bedrock:ap-south-1::foundation-model/apac.amazon.nova-lite-v1:0` | Scoped strictly to Nova-Lite regional model ARN | Prevents unauthorized invocation of expensive Anthropic/Titan models |
| `s3:PutObject`<br>`s3:GetObject` | `arn:aws:s3:::nimbus-ds252-artifacts/*` | Scoped strictly to the project artifact bucket prefix | No wildcard bucket access |

---

## 5. Secrets Manager & Environment Configuration Audit

- **No Plaintext Secrets in Repository**: Full git history scan confirmed 0 AWS secret keys, access tokens, or private credentials committed.
- **Secure ECS Environment Ingestion**: Environment variables in `infra/terraform/main.tf` reference `NIMBUS_AUTH_TOKEN`, `NIMBUS_EDGE_TOKEN`, `NIMBUS_OPERATOR_TOKEN` via SSM Parameter Store / Secrets Manager references.
- **Fail-Closed Runtime**: If tokens are not provided, `server.py` rejects mutating endpoints with `HTTP 401 Unauthorized` rather than failing open.

---

## 6. Amazon S3 and CloudFront Audit

- **Results Bucket (`nimbus-ds252-outputs`)** and **Static App Bucket (`nimbus-ds252-static-app`)**: before red-team issue #25 neither had any of the settings below in Terraform; this section previously described them as present. They are now defined in `infra/terraform/data_protection.tf` (see section 9):
  - `aws_s3_bucket_public_access_block`: all 4 flags (`block_public_acls`, `ignore_public_acls`, `block_public_policy`, `restrict_public_buckets`) are `true`.
  - Server-side encryption: SSE-KMS with the project key (`aws_kms_key.data`), S3 bucket key enabled.
  - Versioning: enabled; noncurrent versions expire after 30 days.
  - Server access logs: written to `nimbus-ds252-access-logs`.
- **CloudFront CDN**: Not deployed in the production Terraform configuration. Static UI assets (`static/requester.html`, `static/operator.html`, `static/app.js`, `static/operator.js`) are served directly by the Python HTTP server via API Gateway HTTP API proxy, eliminating CDN synchronization lag.

---

## 7. Amazon CloudWatch Metrics and Alarms Alignment

- **Log Group**: `/ecs/nimbus-ds252` with 365-day retention, encrypted with the project KMS key (#25; was 30 days, unencrypted by a customer key).
- **ECS Alarms**:
  - `CPUUtilization > 80%` for 2 consecutive periods of 60 seconds.
  - `MemoryUtilization > 85%` for 2 consecutive periods of 60 seconds.
- **Application Health Metric**: Heartbeat misses are detected via `missed_checkin` alarm. Metric namespace matches `Nimbus/Fleet` and dimension `ClusterId` emitted by `cloud/orchestrator.py`. Duplicate skeleton alarm was removed (**C3**).
- **Public Ingress & Security Group (C2)**: Ingress to port 8000 is restricted to `var.allowed_ingress_cidr_blocks` (`["10.20.0.0/16"]`), and `assign_public_ip` is set to `false` by default, eliminating direct Internet exposure.

---

## 8. Image Pinning and Container Egress (red-team issue #20, NFR-5)

- **Image pinned by digest**: the `nimbus-app` ECR repository uses `IMMUTABLE` tags, so a pushed tag can never be re-pushed with other contents. `scripts/build_push.sh` tags each build with the git commit (plus a timestamp for a dirty tree) and refuses `latest`. Terraform resolves `var.app_image_tag` to its digest (`data.aws_ecr_image.app`) and the task definition runs `<repository>@sha256:<digest>`. A manual `var.app_image` must also be a digest reference; a plan with no image stops with a precondition error instead of deploying `:latest`. The ECR lifecycle policy keeps the 10 newest images, so re-apply after pushing; a running digest left behind by more than 10 newer pushes would be expired and the task could not restart.
- **Egress**: the app security group allows outbound TCP 443 only (was: every protocol and port). Every call the container makes is an AWS API over HTTPS (ECR pull, DynamoDB, Bedrock, S3, SQS, IoT data, Secrets Manager, CloudWatch Logs); `NIMBUS_TRANSPORT` is unset in the task definition, so MQTT on 8883 is not used in the cloud.
- **Gateway endpoints**: S3 and DynamoDB traffic, including ECR image layers, goes through free gateway VPC endpoints instead of the internet gateway.
- **Accepted residual risk**: the 443 rule still targets `0.0.0.0/0`, because the regional Bedrock, ECR, SQS, Secrets Manager, Logs and IoT endpoints have no fixed address list a security group can name. Removing it needs about 8 interface VPC endpoints (roughly $8/month each per AZ), more than the $50/month project budget. The exception is marked inline for Trivy (`#trivy:ignore:AVD-AWS-0104`) next to the rule in `infra/terraform/main.tf`, with this reasoning.
- **Regression tests**: `tests/test_p4_issue_20.py`.

---

## 9. Data Protection and Traceability (red-team issue #25, NFR-5, FR-20/NFR-6)

All in `infra/terraform/data_protection.tf`, plus settings on the resources in `main.tf` and `cloud.tf`. Checked with checkov 3.4.5 using the red team's focused command: 24 failed on `main` before the fix, 0 failed (28 passed, 2 justified skips) after.

| Gap (checkov) | Now |
| :--- | :--- |
| S3 public-access block (CKV2_AWS_6) | All three buckets block public ACLs and policies. |
| S3 KMS encryption (CKV_AWS_145) | Results and static-app buckets use SSE-KMS with the project key. The access-log bucket is SSE-S3, because S3 server access logs can only be delivered to an SSE-S3 bucket (inline checkov skip with that reason). |
| S3 versioning (CKV_AWS_21) | Enabled on all three; noncurrent versions expire (30 days for data, 7 for logs). |
| S3 access logging (CKV_AWS_18) | Data buckets log to `nimbus-ds252-access-logs`. The log bucket itself is not logged into itself (inline checkov skip). |
| SQS encryption (CKV_AWS_27) | SSE-SQS on both queues. A KMS-encrypted queue would also need a key grant for the EventBridge target. |
| DynamoDB point-in-time recovery (CKV_AWS_28) | On for all five tables, so the decision log and task state can be restored to any second of the last 35 days. |
| DynamoDB customer-managed key (CKV_AWS_119) | All five tables use the project key. |
| CloudWatch Logs KMS (CKV_AWS_158) | The app and API access log groups use the project key. |
| Log retention (CKV_AWS_338) | 365 days. |
| API Gateway access logs (CKV_AWS_76) | One JSON line per request (request id, source IP, route, status, latency) in `/aws/apigateway/nimbus-ds252-api`. No headers or bodies, so no tokens or request text. |
| VPC flow logs (CKV2_AWS_11) | All traffic, 10-minute aggregation, into the access-log bucket under `vpc-flow-logs/`. |

- **Project key** (`aws_kms_key.data`, alias `alias/nimbus-ds252-data`): rotation on, 30-day deletion window. Its policy follows the AWS-managed `aws/dynamodb` and `aws/s3` keys: any principal in this account that may use a table or bucket may use the key, but only through DynamoDB or S3, so the task role, the edge result uploader and the team's users keep working with no IAM change. CloudWatch Logs may use it for this account's log groups only, and CloudFront for the static-app distribution only. `scripts/audit_iam.py` lists the key-policy wildcards with these reasons.
- **Cost once applied**: the key is $1/month plus requests (S3 bucket keys keep these low); point-in-time recovery, flow logs, access logs and a year of log retention are cents at this project's volume.
- **Not changed**: the new access-log bucket shows the same two checkov findings as the existing buckets, outside #25: CKV_AWS_144 (cross-region replication, which conflicts with the single-region PRD) and CKV2_AWS_62 (event notifications).
- **Regression tests**: `tests/test_p4_issue_25.py`, `infra/terraform/tests/issue_25.tftest.hcl`.
