output "api_endpoint" {
  description = "HTTP API endpoint the requester app and operator console call."
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "escalations_queue_url" {
  description = "SQS queue receiving escalations and check-ins (Person 3's ingress)."
  value       = aws_sqs_queue.escalations.url
}

output "outputs_bucket" {
  description = "S3 bucket for task outputs (result_ref targets)."
  value       = aws_s3_bucket.outputs.bucket
}

output "table_names" {
  description = "DynamoDB tables replacing the local file store."
  value = {
    leases       = aws_dynamodb_table.leases.name
    tasks        = aws_dynamodb_table.tasks.name
    robot_status = aws_dynamodb_table.robot_status.name
    decision_log = aws_dynamodb_table.decision_log.name
  }
}

output "iot_topics" {
  description = "Cloud-edge MQTT topic filters for clients (leases down, escalations/check-ins up). `+` is the MQTT single-level wildcard; the IAM and IoT policies spell the cluster segment as `*` or as the thing name instead."
  value       = local.iot_topics
}

output "alerts_topic_arn" {
  description = "SNS topic the missed check-in alarm notifies; null when alert_email is empty."
  value       = one(aws_sns_topic.alerts[*].arn)
}

output "state_table" {
  description = "Lease/claim/dedupe state table (cloud/aws_dynamo.py)."
  value       = aws_dynamodb_table.state.name
}

output "alb_dns_name" {
  description = "DNS name of internal ALB connecting VPC Link to ECS service."
  value       = aws_lb.internal.dns_name
}

output "vpc_link_id" {
  description = "ID of API Gateway v2 VPC link."
  value       = aws_apigatewayv2_vpc_link.main.id
}
