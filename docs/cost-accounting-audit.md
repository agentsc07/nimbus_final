# Cost Accounting, Telemetry, and AWS Billing Audit

**Target cloud environment:** AWS account `930124786284`, region `ap-south-1`
**Reference components:** `cost.py` (counters and `CostBook`), `server.py` (where counters are recorded),
`results/final/N9/run_n9.py` (prices), `infra/terraform/*.tf`
**Status:** corrected on 12 Nov 2026 (baseline arithmetic, resources Terraform defines, variable names, teardown).
Prices below are the list prices the project used or AWS's published list prices for US East (N. Virginia); prices
for `ap-south-1` were **not verified** and can differ.

---

## 1. Runtime cost metering

`cost.py` records raw counters for each term of the PRD Sec. 7 formula and leaves prices symbolic:

$$\text{Cost}_{\text{task}} = \frac{T_{in} p_{in} + T_{out} p_{out} + F p_{fargate} + M p_{iot} + W p_{ddb} + Q p_{sqs} + S p_{s3} + D p_{transfer} + G p_{apigw} + K p_{cw}}{N_{tasks}}$$

| Counter | What `server.py` records |
| :--- | :--- |
| `input_tokens`, `output_tokens`, `llm_calls` | from the model call (Bedrock `usage` when real; a length/4 estimate for the stand-ins) |
| `fargate_gbs` (F) | wall-clock seconds between ticks x `NIMBUS_FARGATE_GB` (default 1); memory only, there is no vCPU counter |
| `dynamodb_ops` (W) | a fixed count per state change and decision row, not measured read/write capacity units |
| `apigw_requests` (G), `data_transfer_bytes` (D) | one request and the response size for **every** JSON response, including console polling (not separated) |
| `iot_messages` (M), `sqs_messages` (Q), `s3_ops` (S), `cloudwatch_metrics` (K) | per publication, queued message, result upload and emitted metric |

The N9 evaluation (`results/final/N9/run_n9.py`) prices only the token and Fargate terms: Bedrock Nova Lite at
$0.06 per 1M input and $0.24 per 1M output tokens, Fargate at $0.04048 per vCPU-hour and $0.004445 per GB-hour (0.5 vCPU,
1 GB). Those are US East list prices.

---

## 2. Always-on infrastructure (not per task)

What the Terraform on this branch would run with its defaults (`desired_count = 1`, `egress_mode = "public_ip"`):

| Item | Defined in | Rate | Per day | Per 30 days |
| :--- | :--- | :--- | ---: | ---: |
| Fargate task, 0.5 vCPU + 1 GB | `main.tf` (`cpu = 512`, `memory = 1024`) | 0.5 x $0.04048 + 1 x $0.004445 = $0.024685/h | $0.59 | $17.77 |
| Public IPv4 address on the task | `local.assign_public_ip` | $0.005/h | $0.12 | $3.60 |
| Internal Application Load Balancer | `aws_lb.internal` | $0.0225/h + LCU-hours | $0.54 + LCU | $16.20 + LCU |
| Secrets Manager secret | `aws_secretsmanager_secret.app_secrets` | $0.40/secret-month + $0.05 per 10,000 calls | ~$0.01 | $0.40 |
| Container Insights | `aws_ecs_cluster.main` (`containerInsights = enabled`) | CloudWatch custom metrics + performance log ingestion | not measured | not measured |
| CloudWatch Logs `/ecs/nimbus-ds252` (30-day retention), EMF metrics, the alarm | `main.tf` | ingestion, storage, custom metrics, one alarm | not measured | not measured |
| **Total of the measured rows** | | | **~$1.26 + LCU** | **~$38 + LCU** |

Not billed while idle: DynamoDB on-demand tables (per request, plus storage), API Gateway HTTP API (per request; AWS
lists no separate hourly charge for an HTTP API VPC link, not verified on the bill), SQS (the consumer's 10 s long poll makes about 260,000 requests a
month even when idle, inside the 1M-request monthly free tier), the EventBridge bus (no events are published), and the
CloudFront distribution (disabled). There is no NAT gateway.

The deployed stack differs (see `docs/aws-integration-audit.md`): it has no load balancer, and on 12 Nov 2026 both the
C1 and C2 services were scaled to 0, so no Fargate or public-IP charges accrue until they are scaled up again.

**Budget alerts:** `aws_budgets_budget.monthly` is created only when `alert_email` is set; it alerts at 50, 80 and 100 %
of `budget_usd` (default 50 USD) of actual spend. With `alert_email` empty (the default) there are no budget alerts and
no SNS notifications from the missed check-in alarm. There is no variable called `budget_email`.

---

## 3. Teardown

1. **Pause without destroying:** scale the service to zero.
   ```bash
   aws ecs update-service --cluster nimbus-ds252-cluster --service nimbus-ds252-service --desired-count 0 --region ap-south-1
   ```
   The next `terraform apply` sets it back to `desired_count = 1`. The missed check-in alarm on this branch treats the
   missing metrics as breaching, so it goes into ALARM while the service is at zero.
2. **Empty the S3 buckets** `nimbus-ds252-outputs` and `nimbus-ds252-static-app`: they have `force_destroy = false`, so
   `terraform destroy` fails on a bucket that still holds objects. Versioning is off, so this is enough:
   ```bash
   aws s3 rm s3://nimbus-ds252-outputs --recursive --region ap-south-1
   aws s3 rm s3://nimbus-ds252-static-app --recursive --region ap-south-1
   ```
3. **ECR:** `aws_ecr_repository.app` has `force_delete = true`, so `terraform destroy` deletes the `nimbus-app`
   repository together with its images; no manual step is needed.
4. **Destroy:** from the workstation that holds the state file (state is local, see
   `docs/aws-integration-audit.md` section 9):
   ```bash
   terraform -chdir=infra/terraform destroy
   ```
   This permanently deletes the DynamoDB tables, including the decision log (point-in-time recovery is off), and the
   app secret immediately (`recovery_window_in_days = 0`). Export anything you need first.
5. **Resources Terraform does not manage** survive `destroy` and must be removed separately: the C2 stack
   (`nimbus-ds252-c2-service`, API `nimbus-ds252-c2-api`, its task definition, security group, five tables and the
   `nimbus-ds252-c2-escalations` queue).
