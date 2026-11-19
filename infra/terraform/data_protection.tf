# Data protection and traceability for the stores that hold task data, results and the audit trail, and for
# ingress (red-team issue #25, NFR-5, FR-20/NFR-6):
# - one customer-managed KMS key for the DynamoDB tables, the two data buckets and the CloudWatch log groups;
# - public-access blocks, versioning, KMS encryption and access logging on the S3 buckets;
# - an access-log bucket that also receives the VPC flow logs.
# Point-in-time recovery, SQS encryption, log retention and API Gateway access logs are set on the resources
# themselves in main.tf and cloud.tf.
#
# Cost once applied: the key is $1/month plus requests (S3 bucket keys keep those low); point-in-time recovery,
# flow logs, access logs and the year of log retention are cents at this project's volume.

# ---------------------------------------------------------------------------
# The key. Its policy keeps the app working with no IAM change: like the AWS-managed aws/dynamodb and aws/s3
# keys, any principal in this account that may use a table or bucket may use the key, but only through
# DynamoDB or S3 (the task role, the edge result uploader, the team's users). CloudWatch Logs may use it for
# this account's log groups only, and CloudFront for the static-app distribution only.
# In a key policy, Resource "*" means this key.
# ---------------------------------------------------------------------------

resource "aws_kms_key" "data" {
  description             = "Nimbus data at rest: DynamoDB tables, S3 data buckets, CloudWatch log groups (#25)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableIamPolicies"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "UseThroughDynamoDbAndS3"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey", "kms:CreateGrant"]
        Resource  = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = ["dynamodb.${var.aws_region}.amazonaws.com", "s3.${var.aws_region}.amazonaws.com"]
          }
        }
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.aws_region}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
          }
        }
      },
      {
        Sid       = "CloudFrontStaticApp"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey*"]
        Resource  = "*"
        Condition = {
          StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.static_app.arn }
        }
      },
    ]
  })
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name_prefix}-data"
  target_key_id = aws_kms_key.data.key_id
}

# ---------------------------------------------------------------------------
# Access-log bucket: S3 server access logs of the data buckets and the VPC flow logs. S3 can deliver server
# access logs only to an SSE-S3 bucket, so this one bucket is AES256, not KMS. Logs are kept one year.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "access_logs" {
  #checkov:skip=CKV_AWS_145:S3 server access log delivery only supports SSE-S3 (AES256) on the target bucket.
  #checkov:skip=CKV_AWS_18:This is the access-log target itself; logging it into itself would loop.
  bucket        = "${local.name_prefix}-access-logs"
  force_destroy = true # holds only logs, so `terraform destroy` may empty it
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket     = aws_s3_bucket.access_logs.id
  depends_on = [aws_s3_bucket_versioning.access_logs]

  rule {
    id     = "expire-logs-after-a-year"
    status = "Enabled"
    filter {}
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket     = aws_s3_bucket.access_logs.id
  depends_on = [aws_s3_bucket_public_access_block.access_logs]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "S3ServerAccessLogs"
        Effect    = "Allow"
        Principal = { Service = "logging.s3.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.access_logs.arn}/s3-access/*"
        Condition = {
          StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
          ArnLike      = { "aws:SourceArn" = [aws_s3_bucket.outputs.arn, aws_s3_bucket.static_app.arn] }
        }
      },
      {
        Sid       = "VpcFlowLogsWrite"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.access_logs.arn}/vpc-flow-logs/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
            "s3:x-amz-acl"      = "bucket-owner-full-control"
          }
          ArnLike = { "aws:SourceArn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*" }
        }
      },
      {
        Sid       = "VpcFlowLogsAclCheck"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.access_logs.arn
        Condition = {
          StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*" }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Results bucket (task outputs, possibly camera images that are part of a result; NFR-5).
# Versioning keeps an overwritten or deleted result recoverable for 30 days.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket_public_access_block" "outputs" {
  bucket                  = aws_s3_bucket.outputs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "outputs" {
  bucket = aws_s3_bucket.outputs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_logging" "outputs" {
  bucket        = aws_s3_bucket.outputs.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "s3-access/outputs/"
}

resource "aws_s3_bucket_lifecycle_configuration" "outputs" {
  bucket     = aws_s3_bucket.outputs.id
  depends_on = [aws_s3_bucket_versioning.outputs]

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---------------------------------------------------------------------------
# Static web app bucket (CloudFront origin; the distribution is disabled and the UI is served by the container).
# ---------------------------------------------------------------------------

resource "aws_s3_bucket_public_access_block" "static_app" {
  bucket                  = aws_s3_bucket.static_app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "static_app" {
  bucket = aws_s3_bucket.static_app.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static_app" {
  bucket = aws_s3_bucket.static_app.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_logging" "static_app" {
  bucket        = aws_s3_bucket.static_app.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "s3-access/static-app/"
}

resource "aws_s3_bucket_lifecycle_configuration" "static_app" {
  bucket     = aws_s3_bucket.static_app.id
  depends_on = [aws_s3_bucket_versioning.static_app]

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---------------------------------------------------------------------------
# Traceability at the network and ingress boundaries.
# ---------------------------------------------------------------------------

resource "aws_flow_log" "vpc" {
  vpc_id                   = aws_vpc.main.id
  traffic_type             = "ALL"
  log_destination_type     = "s3"
  log_destination          = "${aws_s3_bucket.access_logs.arn}/vpc-flow-logs/"
  max_aggregation_interval = 600
  depends_on               = [aws_s3_bucket_policy.access_logs]

  tags = { Name = "${local.name_prefix}-flow-log" }
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name_prefix}-api"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.data.arn
}
