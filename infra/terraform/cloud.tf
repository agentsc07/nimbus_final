# Person 3 additions to P4's skeleton: lease/claim state table, permissions the
# cloud decision plane needs, internet egress for the Fargate task, and a
# budget alarm. SKELETON ONLY: validate, never apply without the account owner.

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# State table: lease task pointers, robot/zone claims, message-id dedupe,
# task-id counter. TTL on `ttl` expires claims and dedupe ids on their own.
# Item layout is documented in cloud/aws_dynamo.py.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "state" {
  name         = "${local.name_prefix}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true # leases, claims and dedupe ids can be restored to any second of the last 35 days (#25)
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.data.arn # data_protection.tf
  }
}

# ---------------------------------------------------------------------------
# Egress. The skeleton's private subnets had no route out, so the Fargate task
# could neither pull its image nor reach Bedrock. "public_ip" (default) is the
# cheapest working option: an internet gateway and a public IP per task, with
# nothing listening (no inbound security-group rules). A NAT gateway costs
# roughly $32+/month, so it is deliberately not the default.
# ---------------------------------------------------------------------------

resource "aws_internet_gateway" "main" {
  count  = var.egress_mode == "public_ip" ? 1 : 0
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name_prefix}-igw" }
}

resource "aws_route_table" "egress" {
  count  = var.egress_mode == "public_ip" ? 1 : 0
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }
}

resource "aws_route_table_association" "egress_a" {
  count          = var.egress_mode == "public_ip" ? 1 : 0
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.egress[0].id
}

resource "aws_route_table_association" "egress_b" {
  count          = var.egress_mode == "public_ip" ? 1 : 0
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.egress[0].id
}

# S3 and DynamoDB (every table call, task results, and the image layers ECR serves from S3) go
# through gateway endpoints, which cost nothing, so that traffic stays on the AWS network instead
# of the internet gateway (#20). Without "public_ip" the subnets use the VPC's main route table.
locals {
  task_route_table_ids = var.egress_mode == "public_ip" ? [aws_route_table.egress[0].id] : [aws_vpc.main.main_route_table_id]
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.task_route_table_ids
  tags              = { Name = "${local.name_prefix}-s3-endpoint" }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.task_route_table_ids
  tags              = { Name = "${local.name_prefix}-dynamodb-endpoint" }
}

# ---------------------------------------------------------------------------
# Permissions the decision plane needs beyond P4's baseline policy.
# - state table (conditional writes and transactions use Put/Update/Delete)
# - Scan on tasks (startup recovery of queued work)
# - Bedrock: Converse needs bedrock:InvokeModel. Cross-region inference
#   profiles route to other regions, so the foundation-model ARN is region-wild
#   and the profile ARN is account-scoped.
# - IoT topics exactly as contracts/topics.md names them (P4's iot_topics
#   locals use a different pattern, which would deny these publishes).
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "task_p3" {
  name = "${local.name_prefix}-task-policy-p3"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StateTable"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
          "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
          # cloud/aws_dynamo.py commits a lease, its robot claims and the stock count in one transaction.
          "dynamodb:TransactWriteItems",
        ]
        Resource = [aws_dynamodb_table.state.arn]
      },
      {
        Sid      = "TasksScan"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan"]
        Resource = [aws_dynamodb_table.tasks.arn]
      },
      {
        Sid    = "BedrockConverse"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/*",
        ]
      },
      {
        Sid    = "IotPublish"
        Effect = "Allow"
        Action = ["iot:Publish"]
        Resource = [
          for t in ["lease", "renewal", "probe", "notice"] :
          "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/nimbus/*/${t}"
        ]
      },
      {
        Sid    = "ResultsAndLogs"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.outputs.arn}/results/*",
          "${aws_s3_bucket.outputs.arn}/logs/*",
          "${aws_s3_bucket.outputs.arn}/bundles/*",
        ]
      },
      {
        Sid      = "ResultsHead"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.outputs.arn]
      },
      {
        Sid      = "EdgeQueue"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
        Resource = aws_sqs_queue.escalations.arn
      },
      {
        Sid      = "RuleKnowledgeBase"
        Effect   = "Allow"
        Action   = ["bedrock:Retrieve"]
        Resource = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:knowledge-base/*"
      },
      {
        Sid    = "IotSubscribe"
        Effect = "Allow"
        Action = ["iot:Subscribe", "iot:Receive"]
        Resource = [
          for t in ["escalation", "checkin"] :
          "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/nimbus/*/${t}"
        ]
      },
      {
        Sid      = "AppSecretsRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = [aws_secretsmanager_secret.app_secrets.arn]
      },

    ]
  })
}

# ---------------------------------------------------------------------------
# Dead-letter queue for edge messages the cloud cannot handle. cloud/sqs_consumer.py deletes a message that keeps failing
# after max_receives; with this redrive policy SQS moves it here first (after 5 receives), so nothing is lost silently.
# The redrive policy is a separate resource so the queue itself (P4's main.tf) is not edited.
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "escalations_dlq" {
  name                      = "${local.name_prefix}-escalations-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true # SSE-SQS, same as the main queue (#25)
}

resource "aws_sqs_queue_redrive_policy" "escalations" {
  queue_url = aws_sqs_queue.escalations.id
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.escalations_dlq.arn
    maxReceiveCount     = 5
  })
}

# ---------------------------------------------------------------------------
# Cost guard (PRD risk R3: budget alarms from week 1). Created only when an
# alert address is given.
# ---------------------------------------------------------------------------

resource "aws_budgets_budget" "monthly" {
  count        = var.alert_email == "" ? 0 : 1
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# ---------------------------------------------------------------------------
# Container registry for the service image (the Dockerfile is P3's). The image is
# built and pushed by scripts/build_push.sh. First deploy: apply just the repository
# (`terraform apply -target=aws_ecr_repository.app`), push the image, then apply the rest,
# otherwise the ECS service starts before there is an image to pull.
#
# What ECS runs is pinned (#20): tags are immutable, so a pushed tag can never point at
# other contents later, and the task definition names the image by digest, not by tag.
# Deploy with `-var app_image_tag=<the tag build_push.sh printed>`; there is no `latest`.
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  name                 = "nimbus-app"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# var.app_image_tag resolved to its digest at plan time. Not read when var.app_image already
# names a digest, or when no tag is given (the task definition's precondition then stops the plan).
data "aws_ecr_image" "app" {
  count           = var.app_image == "" && var.app_image_tag != "" ? 1 : 0
  repository_name = aws_ecr_repository.app.name
  image_tag       = var.app_image_tag
}

locals {
  app_image = var.app_image != "" ? var.app_image : (
    length(data.aws_ecr_image.app) == 1 ? "${aws_ecr_repository.app.repository_url}@${data.aws_ecr_image.app[0].image_digest}" : ""
  )
}

output "ecr_repository_url" {
  description = "Where scripts/build_push.sh pushes the service image."
  value       = aws_ecr_repository.app.repository_url
}
