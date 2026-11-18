# Red-team issue #25: data stores and ingress are encrypted, recoverable and logged.
# Runs offline against a mocked AWS provider (no credentials, nothing created):
#   cd infra/terraform && terraform init && terraform test

mock_provider "aws" {
  source = "./tests/mocks"
}

run "data_stores_and_ingress_are_protected" {
  command = apply
  variables { app_image_tag = "3f2a1b9c0d1e" }

  assert {
    condition = alltrue([for table in [aws_dynamodb_table.state, aws_dynamodb_table.leases, aws_dynamodb_table.tasks, aws_dynamodb_table.robot_status, aws_dynamodb_table.decision_log] :
    table.point_in_time_recovery[0].enabled && table.server_side_encryption[0].enabled && table.server_side_encryption[0].kms_key_arn == aws_kms_key.data.arn])
    error_message = "every table needs point-in-time recovery and the project KMS key"
  }
  assert {
    condition     = alltrue([for queue in [aws_sqs_queue.escalations, aws_sqs_queue.escalations_dlq] : queue.sqs_managed_sse_enabled])
    error_message = "both queues must be encrypted"
  }
  assert {
    condition = alltrue([for group in [aws_cloudwatch_log_group.app, aws_cloudwatch_log_group.api_access] :
    group.kms_key_id == aws_kms_key.data.arn && group.retention_in_days >= 365])
    error_message = "log groups must use the project key and keep a year"
  }
  assert {
    condition = alltrue([for block in [aws_s3_bucket_public_access_block.outputs, aws_s3_bucket_public_access_block.static_app, aws_s3_bucket_public_access_block.access_logs] :
    block.block_public_acls && block.block_public_policy && block.ignore_public_acls && block.restrict_public_buckets])
    error_message = "every bucket must block public access"
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.access_log_settings[0].destination_arn == aws_cloudwatch_log_group.api_access.arn
    error_message = "the API stage must write access logs"
  }
  assert {
    condition     = aws_flow_log.vpc.vpc_id == aws_vpc.main.id && aws_flow_log.vpc.traffic_type == "ALL"
    error_message = "the VPC needs flow logs"
  }
  assert {
    condition     = aws_kms_key.data.enable_key_rotation
    error_message = "the project key must rotate"
  }
}
