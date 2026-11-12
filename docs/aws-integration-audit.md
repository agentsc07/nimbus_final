# AWS Infrastructure and Service Integration Audit

**Target environment:** AWS account `930124786284`, region `ap-south-1`
**ECS service:** `nimbus-ds252-service` (cluster `nimbus-ds252-cluster`)
**Sources:** `infra/terraform/*.tf` on this branch (what the code *defines*), and a read-only inspection of the live
account on 12 Nov 2026 (describe/list/get calls only, recorded in the red-team report). The two differ, so every
section below says which one it describes.
**Status:** corrected on 12 Nov 2026. An earlier version of this page marked IoT/MQTT/SQS as "Validated" and listed
controls (S3 hardening, CPU/memory alarms, a Nova-Lite-only Bedrock grant, a 300 s visibility timeout) that neither the
Terraform nor the account contains. Those claims are withdrawn.

---

## 0. Defined in Terraform vs. deployed

The Terraform in this repository has **never been applied as it stands**. The live stack was created on 7 Nov 2026 from
an earlier configuration (local state, serial 67, 46 resources), and the image it runs predates the fail-closed
authentication now in `server.py`.

| Area | Terraform on this branch | Live on 12 Nov 2026 |
| :--- | :--- | :--- |
| Ingress | API Gateway HTTP API -> VPC link -> internal ALB (port 80) -> tasks on 8000 | API Gateway `qrgdidp9te`, routes `ANY /{proxy+}` and `GET /`, no authorizer, integrations `HTTP_PROXY` over the **internet** to a hard-coded `http://<task public IP>:8000`; no VPC link, no load balancer, no throttling, no access logs |
| Task networking | public IP when `egress_mode = "public_ip"` (default), inbound 8000 only from the ALB security group | `assignPublicIp ENABLED`, security group allows tcp/8000 from `0.0.0.0/0` |
| Image | `var.app_image`, default `nimbus-app:latest` | tag `hospital-sim6-r2fix` (pushed 7 Nov), task definition `nimbus-ds252-app:12` |
| App tokens | four `NIMBUS_*_TOKEN` values injected from Secrets Manager | no `secrets` block and no token variables; the secret exists with 0 versions |
| Service size | `desired_count = 1` | scaled to 0 (not serving) |
| SQS | queue + DLQ + redrive after 5 receives | queue only (`nimbus-ds252-escalations`, plus an unmanaged `nimbus-ds252-c2-escalations`); no DLQ, no redrive |
| EventBridge | bus + rule + SQS target | bus only, no rules |
| IoT Core | edge policy | policy exists; 0 things, 0 certificates |
| CloudWatch | missed check-in alarm (fixed on this branch, see section 7) | alarm on a metric nobody emits, 0 actions |
| C2 stack | not defined | `nimbus-ds252-c2-*` service, API (`xkczmnuqla`), tables and queue exist, unmanaged |

Consequences: with the deployed image every route except `/fault` and `/llm/outage` was unauthenticated, and the
container was reachable directly from the internet, bypassing API Gateway. Applying this branch's Terraform as it is
would replace the task with one that cannot start until the four token keys are written to the secret (ECS cannot
resolve the `secrets` references of an empty secret).

---

## 1. AWS IoT Core / MQTT

**Status: not deployed and not functional.**

- The edge has no MQTT client; edges talk to the cloud over HTTP only (`docs/EDGE_CLOUD_PROTOCOL.md` section 2).
- `mqtt_transport.py` is used only when `NIMBUS_TRANSPORT=mqtt`. Its paho client connects in plaintext on port 1883 with
  no TLS and no credentials, which AWS IoT Core does not accept. `paho-mqtt` is not in `requirements.txt`, so without it
  the server falls back to an in-process stand-in broker from which no message leaves the process (this now logs a
  WARNING). The live task definition sets `NIMBUS_TRANSPORT=mqtt`; whether the deployed image contains paho was not
  verified.
- Messages the server receives over MQTT go to the same ingest functions as `POST /checkins` and `POST /escalations`
  but without the HTTP token check, so MQTT must only be enabled with a broker that authenticates its clients.
- Live: 0 things and 0 certificates.

IoT permissions in Terraform after this branch (none of them is exercised by anything deployed):

| Principal | Allowed | Resources |
| :--- | :--- | :--- |
| Edge policy `nimbus-ds252-edge-policy` | `iot:Connect` | `client/${iot:Connection.Thing.ThingName}` |
| | `iot:Publish` (edge -> cloud) | `topic/nimbus/${iot:Connection.Thing.ThingName}/{escalation,checkin}` |
| | `iot:Receive` (cloud -> edge) | `topic/nimbus/${iot:Connection.Thing.ThingName}/{lease,renewal,probe,notice}` |
| | `iot:Subscribe` | `topicfilter/nimbus/${iot:Connection.Thing.ThingName}/{lease,renewal,probe,notice}` |
| Task role | `iot:Connect` | `client/nimbus-ds252-*` |
| | `iot:Publish` | `topic/nimbus/*/{lease,renewal,probe,notice}` |
| | `iot:Receive` / `iot:Subscribe` | `topic/` / `topicfilter/nimbus/*/{escalation,checkin}` |

Onboarding requirement for the per-cluster scoping: the IoT thing name must equal the cluster id (for example
`east-wing`), the cluster's certificate must be attached to that thing, and the MQTT client id must be the same name.
Earlier versions used the MQTT wildcard `+` inside IAM ARNs (IAM reads it as a literal character, so those grants
matched nothing), put `iot:Subscribe` on `topic/` ARNs (denied), let the edge publish `probe` (a cloud -> edge topic) but
not receive it, and let any certificate act as any cluster.

---

## 2. Amazon SQS

| Property | Terraform | Live / code |
| :--- | :--- | :--- |
| Queue | `nimbus-ds252-escalations` (`main.tf`) | exists |
| Visibility timeout | 30 s (queue default) | 30 s; `cloud/sqs_consumer.py` asks for 120 s on each `ReceiveMessage` |
| Dead-letter queue | `nimbus-ds252-escalations-dlq`, redrive after 5 receives (`cloud.tf`) | **not deployed**; the consumer deletes a message after 6 receives as a backstop |
| Task-role permissions | `SendMessage`, `ReceiveMessage` (`main.tf` `Queue`); `ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes`, `ChangeMessageVisibility` (`cloud.tf` `EdgeQueue`), all on the queue ARN | not compared |

Nothing in the repository publishes edge messages to this queue (no IoT topic rule is defined), so the consumer only
sees messages someone sends by hand.

---

## 3. Amazon EventBridge

`main.tf` defines bus `nimbus-ds252-bus`, rule `nimbus-ds252-task-events` and an SQS target. No code publishes to the bus
(nothing calls `events:PutEvents`), and the queue has no policy that would let EventBridge deliver to it. Live, only the
bus exists. The resources are kept so that an apply does not delete live resources; nothing relies on them.

---

## 4. IAM least privilege

Task role `nimbus-ds252-task-role` (policies `nimbus-ds252-task-policy` in `main.tf` and `nimbus-ds252-task-policy-p3`
in `cloud.tf`):

| Actions | Resources | Note |
| :--- | :--- | :--- |
| DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query`, `TransactWriteItems`, `TransactGetItems`, `DescribeTable` | the four tables `leases`, `tasks`, `robot_status`, `decision_log` (exact ARNs) | |
| DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query`, `Scan`, `TransactWriteItems` | the `state` table | |
| DynamoDB `Scan` | the `tasks` table | startup recovery |
| `bedrock:InvokeModel` | `arn:aws:bedrock:ap-south-1::foundation-model/*` and `arn:aws:bedrock:*::foundation-model/*`, plus this account's `inference-profile/*` | **any model in any region**, needed for the `apac.` cross-region inference profile; not limited to Nova Lite |
| `bedrock:Retrieve` | this account's `knowledge-base/*` | |
| S3 `GetObject`, `PutObject` | `nimbus-ds252-outputs/*` (and `results/*`, `logs/*`, `bundles/*` under it); `ListBucket` on the bucket | |
| SQS, IoT | see sections 1 and 2 | |
| `events:PutEvents` | the project bus | unused |
| `secretsmanager:GetSecretValue`, `DescribeSecret` | the app secret | |

Execution role: the AWS managed `AmazonECSTaskExecutionRolePolicy` plus `secretsmanager:GetSecretValue` on the app
secret. `scripts/audit_iam.py` checks every Terraform and JSON policy statement (with or without a Sid) for `*` actions,
`service:*` actions, `*` resources and `NotAction`/`NotResource`; the only wildcards it reports are the two justified
ones in `infra/iam/p3-dev-policy.json` (a developer policy, not the task role).

---

## 5. Secrets Manager, tokens and secret scanning

- Terraform: the task definition injects `NIMBUS_REQUESTER_TOKEN`, `NIMBUS_OPERATOR_TOKEN`, `NIMBUS_EDGE_TOKEN` and
  `NIMBUS_ADMIN_TOKEN` from JSON keys of secret `nimbus-ds252-app-secrets`. `NIMBUS_AUTH_TOKEN` (master) is not injected.
  The values are written by hand; Terraform does not create them, and there is no rotation.
- Live: the secret has 0 versions, and the running task definition does not reference it (see section 0).
- Code on this branch: `server.py` fails closed when a role's token is not configured (401, or 403 for the admin routes);
  `NIMBUS_AUTH_DISABLED=1` is ignored in production mode. See `docs/security-endpoint-matrix.md`.
- Scanning: `python scripts/audit_iam.py` scans every git-tracked text file; `--history` scans every line added on any
  ref. Run on this branch on 12 Nov 2026, both reported 0 findings (placeholder values such as those in
  `.env.example` are allowlisted and listed in the report). `.gitignore` excludes `.env`, `.env.*` (except
  `.env.example`) and `*.tfvars`.

---

## 6. Amazon S3 and CloudFront

- Terraform declares buckets `nimbus-ds252-outputs` and `nimbus-ds252-static-app` with **no** public-access-block,
  encryption, versioning, ownership or lifecycle resources.
- Live, both buckets have all four public-access-block flags on, AES256 default encryption and `BucketOwnerEnforced`
  ownership (the AWS defaults for new buckets, not Terraform-managed), versioning off and no lifecycle rule, so a result
  can be overwritten.
- CloudFront: `main.tf` defines a distribution with `enabled = false`; live it exists and is disabled. The UI
  (`static/index.html`, `static/operator.html`, `static/map.html`, `static/app.js`, `static/operator.js`) is served by
  `server.py` itself.

---

## 7. CloudWatch

- Log group `/ecs/nimbus-ds252`, 30-day retention; Container Insights is enabled on the ECS cluster.
- There are **no** CPU or memory alarms.
- Metrics: with `NIMBUS_EMF=1` (set in the task definition) `server.py` prints an Embedded Metric Format line about every
  60 s: namespace `Nimbus`, dimensions `Service=nimbus-cloud` and `Pack=<pack>`, metrics `QueueDepth`, `LiveLeases`,
  `LlmCallsSinceLast`, `HealthyClusters`, and `RequestToLeaseP95` / `LlmLatencyP95` once observed. Whether CloudWatch
  extracted these metrics in the live account was not verified.
- Missed check-in alarm `nimbus-ds252-missed-checkin-alarm`: it watched `Nimbus/App MissedCheckins`, which no code emits,
  and has 0 actions live. This branch points it at `Nimbus HealthyClusters` (`Service=nimbus-cloud`,
  `Pack=var.metrics_pack`, default `hospital_sim6`), alarming when the minimum over 120 s is below
  `var.expected_clusters` (default 2) in 2 of 2 periods; missing data counts as breaching (the service is down or not
  emitting, which includes being scaled to 0). An SNS topic and e-mail subscription are created only when `alert_email`
  is set; the recipient must confirm the subscription. Not yet applied. The alarm only notifies: re-planning after
  missed check-ins is done by the application's ticker.
- Budget: `aws_budgets_budget.monthly` (50/80/100 % of `budget_usd`) exists only when `alert_email` is set.

---

## 8. Network and egress

- Terraform: the two subnets are named "private" but, with `egress_mode = "public_ip"` (default), route to an internet
  gateway, and the tasks get a public IP. There is no NAT gateway and there are no VPC endpoints. Until this branch the
  public IP defaulted to `false`, so with the defaults a task could not pull its image or reach Bedrock, Secrets Manager
  or DynamoDB; `assign_public_ip` is now derived from `egress_mode` (`var.assign_public_ip` still overrides it).
- Inbound port 8000 is allowed only from the internal ALB's security group. `var.allowed_ingress_cidr_blocks` and
  `var.ecs_target_url` are not used by any resource.

---

## 9. State and deployment reproducibility

- State is a local `terraform.tfstate` on one workstation (gitignored) with no locking. `main.tf` now carries a
  commented-out S3 + DynamoDB `backend` block with migration steps; it is not active.
- `scripts/build_push.sh` tags each image with the git short SHA (plus `-dirty` for uncommitted changes) and `latest`,
  and prints the `-var app_image=...` (tag and digest) to apply. Pushing a new `latest` alone does not redeploy anything.
- ECR tags stay `MUTABLE` because `latest` is moved on every push; pin deployments by commit tag or digest.
- The ECR repository name `nimbus-app` is fixed, so a second stack (e.g. C2) cannot be created from this configuration
  with a different `project_name` without a name clash; the live C2 stack is outside Terraform and `terraform destroy`
  leaves it behind.

---

## 10. Open items (not changed on this branch)

- S3 public-access-block, encryption, versioning and lifecycle are not expressed in Terraform.
- DynamoDB point-in-time recovery is off and deletion protection is off; `terraform destroy` deletes the decision log.
- API Gateway has no authorizer, throttling or access logging.
- MQTT has no TLS or client authentication; do not enable `NIMBUS_TRANSPORT=mqtt` in production.
- The AWS CLI profile used for the 12 Nov inspection authenticates as the account root user; day-to-day work should use
  an IAM role or user with MFA.
